import sys
import grpc

import dservice_pb2
import dservice_pb2_grpc
import hservice_pb2
import hservice_pb2_grpc


def run_client(username: str, password: str, message: str):
    data_ip = '127.0.0.1'
    data_port = 50051
    hash_ip = '127.0.0.1'
    hash_port = 50052

    d_channel = grpc.insecure_channel(f'{data_ip}:{data_port}')
    d_stub = dservice_pb2_grpc.DBStub(d_channel)

    res = d_stub.RegisterUser(dservice_pb2.UserPass(username=username, password=password))
    print('RegisterUser:', 'success' if res.success else 'already exists or failure')

    res2 = d_stub.StoreData(dservice_pb2.StoreReq(username=username, password=password, msg=message))
    print('StoreData:', 'success' if res2.success else 'failure')

    p = d_stub.GenPasscode(dservice_pb2.UserPass(username=username, password=password))
    passcode = p.code
    print('GenPasscode:', passcode)

    h_channel = grpc.insecure_channel(f'{hash_ip}:{hash_port}')
    h_stub = hservice_pb2_grpc.HSStub(h_channel)
    resp = h_stub.GetHash(hservice_pb2.Request(passcode=passcode, ip=data_ip, port=data_port))
    print('Hash:', resp.hash)


if __name__ == '__main__':
    if len(sys.argv) >= 4:
        username = sys.argv[1]
        password = sys.argv[2]
        message = sys.argv[3]
    run_client(username, password, message)