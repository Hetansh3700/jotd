// vault-screen-ocr — one-shot, on-device OCR for the vault screen-capture client.
//
//   usage: vault-screen-ocr <png-path>
//   output: one JSON object on stdout: {"text": str, "app": str|null, "title": str|null}
//
// Deliberately different from streaming/ambient OCR settings: .accurate recognition
// with language correction ON (this text persists into notes; latency budget is one
// second, once), no token filtering, no confidence floor (a still PNG of a chosen
// region has no scroll blur — silently dropping lines from an intentional grab is
// worse than keeping noise).
//
// TCC surface: NONE. Vision on a PNG file and NSWorkspace.frontmostApplication need
// no permission; CGWindowListCopyWindowInfo window NAMES require Screen Recording but
// silently come back empty rather than prompting — and that grant already exists for
// the responsible process, or `screencapture -i` upstream could not have produced the
// PNG this helper is reading.

import AppKit
import Vision

// MARK: - image loading

guard CommandLine.arguments.count == 2 else {
    FileHandle.standardError.write("usage: vault-screen-ocr <png-path>\n".data(using: .utf8)!)
    exit(2)
}
let path = CommandLine.arguments[1]
guard
    let source = CGImageSourceCreateWithURL(URL(fileURLWithPath: path) as CFURL, nil),
    let loaded = CGImageSourceCreateImageAtIndex(source, 0, nil)
else {
    FileHandle.standardError.write("cannot read image: \(path)\n".data(using: .utf8)!)
    exit(1)
}

// Flatten onto white: text on a TRANSPARENT background composites to black-on-black
// inside Vision and reads as blank. Screencapture output is opaque, but arbitrary
// PNGs (tests, other clients) may not be.
func flattened(_ img: CGImage) -> CGImage {
    guard img.alphaInfo != .none, img.alphaInfo != .noneSkipFirst, img.alphaInfo != .noneSkipLast,
        let ctx = CGContext(
            data: nil,
            width: img.width,
            height: img.height,
            bitsPerComponent: 8,
            bytesPerRow: 0,
            space: CGColorSpaceCreateDeviceRGB(),
            bitmapInfo: CGImageAlphaInfo.noneSkipLast.rawValue
        )
    else { return img }
    let rect = CGRect(x: 0, y: 0, width: img.width, height: img.height)
    ctx.setFillColor(CGColor(red: 1, green: 1, blue: 1, alpha: 1))
    ctx.fill(rect)
    ctx.draw(img, in: rect)
    return ctx.makeImage() ?? img
}

let image = flattened(loaded)

// MARK: - OCR

let request = VNRecognizeTextRequest()
request.recognitionLevel = .accurate
request.usesLanguageCorrection = true

try? VNImageRequestHandler(cgImage: image, options: [:]).perform([request])

struct Word {
    let text: String
    let box: CGRect  // Vision-normalized, origin bottom-left
}

var words: [Word] = []
for observation in request.results ?? [] {
    guard let candidate = observation.topCandidates(1).first else { continue }
    let text = candidate.string.trimmingCharacters(in: .whitespacesAndNewlines)
    if !text.isEmpty {
        words.append(Word(text: text, box: observation.boundingBox))
    }
}

// MARK: - line reassembly: group by >50% vertical overlap, left-to-right within a line

func overlaps(_ a: CGRect, _ b: CGRect) -> Bool {
    let shared = min(a.maxY, b.maxY) - max(a.minY, b.minY)
    return shared > 0.5 * min(a.height, b.height)
}

var lines: [[Word]] = []
for word in words.sorted(by: { $0.box.midY > $1.box.midY }) {
    if var last = lines.last, let anchor = last.first, overlaps(anchor.box, word.box) {
        last.append(word)
        lines[lines.count - 1] = last
    } else {
        lines.append([word])
    }
}

// MARK: - redaction: drop password LINES (not the whole grab)
//
// Vision reads on-screen password bullets (••••) as PERIODS, so matching bullet
// characters alone misses the real leak shape. Bare dot-runs can't be dropped
// blanket-style either — terminal dot-leaders ("checks......: 100%") are content.
// Rule: drop a line with a literal bullet/asterisk run, OR "password" followed by
// any masked run (bullets, dots, or asterisks).

let bullets = try! NSRegularExpression(
    pattern: "[•●]{4,}|\\*{6,}|(?i:password)\\s*:?\\s*[•●.*]{4,}"
)
func containsBullets(_ s: String) -> Bool {
    bullets.firstMatch(in: s, range: NSRange(s.startIndex..., in: s)) != nil
}

let text = lines
    .map { line in line.sorted { $0.box.minX < $1.box.minX }.map(\.text).joined(separator: " ") }
    .filter { !containsBullets($0) }
    .joined(separator: "\n")

// MARK: - frontmost app + window title (best effort; omit rather than guess)

var appName: String?
var title: String?
if let front = NSWorkspace.shared.frontmostApplication {
    appName = front.localizedName
    let options: CGWindowListOption = [.optionOnScreenOnly, .excludeDesktopElements]
    let windows = CGWindowListCopyWindowInfo(options, kCGNullWindowID) as? [[String: Any]] ?? []
    for window in windows {
        guard
            window[kCGWindowOwnerPID as String] as? pid_t == front.processIdentifier,
            window[kCGWindowLayer as String] as? Int == 0,
            let name = window[kCGWindowName as String] as? String,
            !name.isEmpty
        else { continue }
        title = name
        break
    }
}

// MARK: - emit contract JSON

let payload: [String: Any] = [
    "text": text,
    "app": appName ?? NSNull(),
    "title": title ?? NSNull(),
]
let data = try! JSONSerialization.data(withJSONObject: payload, options: [.sortedKeys])
FileHandle.standardOutput.write(data)
FileHandle.standardOutput.write("\n".data(using: .utf8)!)
