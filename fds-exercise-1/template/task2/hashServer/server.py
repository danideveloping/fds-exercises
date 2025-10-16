import grpc
import hashlib
from concurrent import futures

import hservice_pb2
import hservice_pb2_grpc
import dservice_pb2
import dservice_pb2_grpc


class HashServer(hservice_pb2_grpc.HSServicer):
    def GetHash(self, request, context):
        target = f"{request.ip}:{request.port}"
        with grpc.insecure_channel(target) as channel:
            d_stub = dservice_pb2_grpc.DBStub(channel)
            data = d_stub.GetAuthData(dservice_pb2.Passcode(code=request.passcode))

        msg = data.msg if data and hasattr(data, 'msg') else ''
        digest = hashlib.sha256(msg.encode('utf-8')).hexdigest()
        return hservice_pb2.Response(hash=digest)


def serve(port: int = 50052):
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    hservice_pb2_grpc.add_HSServicer_to_server(HashServer(), server)
    server.add_insecure_port(f"[::]:{port}")
    server.start()
    print(f"Hash server listening on port {port}")
    server.wait_for_termination()


if __name__ == '__main__':
    serve(50052)