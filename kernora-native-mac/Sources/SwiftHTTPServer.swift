// Kernora — AI Work Intelligence
// Elastic License 2.0 — commercial use requires agreement with kernora.ai
// https://github.com/kernora-ai/nora/blob/main/LICENSE
import Foundation
import Network

class MinimalHTTPServer {
    private let listener: NWListener
    private let queue = DispatchQueue(label: "kernora.http.server")
    var requestHandler: ((String, String, Data) -> (Int, Data))?
    let port: UInt16

    init(port: UInt16) throws {
        self.port = port
        let params = NWParameters.tcp
        params.requiredInterfaceType = .loopback
        
        self.listener = try NWListener(using: params, on: NWEndpoint.Port(rawValue: port)!)
    }

    func start() {
        listener.newConnectionHandler = { [weak self] connection in
            self?.handleConnection(connection)
        }
        listener.stateUpdateHandler = { [weak self] state in
            switch state {
            case .ready:
                print("Kernora LLM server listening on :\(self?.port ?? 0)")
            case .failed(let error):
                print("Server failed with \(error)")
                exit(1)
            default:
                break
            }
        }
        listener.start(queue: queue)
    }

    private func handleConnection(_ connection: NWConnection) {
        connection.start(queue: self.queue)
        var buffer = Data()
        
        func receive() {
            connection.receive(minimumIncompleteLength: 1, maximumLength: 65536) { [weak self] data, _, isComplete, error in
                guard let self = self else { return }
                if let data = data {
                    buffer.append(data)
                    if let separatorRange = buffer.range(of: Data("\r\n\r\n".utf8)) {
                        let headerData = buffer.subdata(in: 0..<separatorRange.lowerBound)
                        let reqString = String(data: headerData, encoding: .utf8) ?? ""
                        var contentLength = 0
                        var method = ""
                        var path = ""
                        
                        let lines = reqString.components(separatedBy: "\r\n")
                        if let firstLine = lines.first {
                            let parts = firstLine.components(separatedBy: " ")
                            if parts.count >= 2 {
                                method = parts[0]
                                path = parts[1]
                            }
                        }
                        
                        for line in lines {
                            let lower = line.lowercased()
                            if lower.starts(with: "content-length:") {
                                let parts = line.components(separatedBy: ":")
                                if parts.count == 2 {
                                    contentLength = Int(parts[1].trimmingCharacters(in: .whitespaces)) ?? 0
                                }
                            }
                        }
                        
                        let bodyStartIndex = separatorRange.upperBound
                        let bodyDataSoFar = buffer.subdata(in: bodyStartIndex..<buffer.count)
                        
                        if bodyDataSoFar.count >= contentLength {
                            let body = bodyDataSoFar.subdata(in: 0..<contentLength)
                            self.processRequest(method: method, path: path, body: body, connection: connection)
                        } else {
                            let remaining = contentLength - bodyDataSoFar.count
                            self.receiveFixedBody(connection: connection, remaining: remaining, currentBody: bodyDataSoFar, method: method, path: path)
                        }
                    } else {
                        if !isComplete {
                            receive()
                        }
                    }
                } else if isComplete || error != nil {
                    connection.cancel()
                }
            }
        }
        receive()
    }
    
    private func receiveFixedBody(connection: NWConnection, remaining: Int, currentBody: Data, method: String, path: String) {
        var collected = currentBody
        var leftToRead = remaining
        func recvNext() {
            connection.receive(minimumIncompleteLength: min(1, leftToRead), maximumLength: leftToRead) { [weak self] data, _, isComplete, error in
                guard let self = self else { return }
                if let data = data {
                    collected.append(data)
                    leftToRead -= data.count
                    if leftToRead <= 0 {
                        self.processRequest(method: method, path: path, body: collected, connection: connection)
                        return
                    }
                }
                if isComplete || error != nil {
                    connection.cancel()
                } else {
                    recvNext()
                }
            }
        }
        recvNext()
    }
    
    private func processRequest(method: String, path: String, body: Data, connection: NWConnection) {
        guard let handler = requestHandler else {
            self.sendResponse(connection: connection, statusCode: 404, body: Data())
            return
        }
        let (status, respBody) = handler(method, path, body)
        self.sendResponse(connection: connection, statusCode: status, body: respBody)
    }
    
    private func sendResponse(connection: NWConnection, statusCode: Int, body: Data) {
        var statusString = "OK"
        if statusCode == 400 { statusString = "Bad Request" }
        else if statusCode == 404 { statusString = "Not Found" }
        else if statusCode == 500 { statusString = "Internal Server Error" }
        else if statusCode == 503 { statusString = "Service Unavailable" }

        let responseHeaders = """
        HTTP/1.1 \(statusCode) \(statusString)\r
        Connection: close\r
        Content-Length: \(body.count)\r
        Content-Type: application/json\r
        \r
        
        """
        var responseData = responseHeaders.data(using: .utf8)!
        responseData.append(body)
        
        connection.send(content: responseData, completion: .contentProcessed { _ in
            connection.cancel()
        })
    }
}
