// OCR tiếng Việt bằng Apple Vision (macOS). Dùng: vision_ocr ảnh1.png [ảnh2.png ...]
// In ra mỗi dòng: "<số trang theo thứ tự ảnh>\t<độ tin cậy 0-100>\t<chữ>"
import Foundation
import Vision

for (i, path) in CommandLine.arguments.dropFirst().enumerated() {
    let req = VNRecognizeTextRequest()
    req.recognitionLevel = .accurate
    req.recognitionLanguages = ["vi-VT"]
    req.usesLanguageCorrection = true
    do {
        try VNImageRequestHandler(url: URL(fileURLWithPath: path)).perform([req])
    } catch {
        FileHandle.standardError.write("lỗi \(path): \(error)\n".data(using: .utf8)!)
        continue
    }
    for obs in req.results ?? [] {
        if let c = obs.topCandidates(1).first {
            print("\(i)\t\(Int(c.confidence * 100))\t\(c.string)")
        }
    }
}
