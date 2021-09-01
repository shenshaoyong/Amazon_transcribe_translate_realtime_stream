# Tested using Python 3.7.7
import hashlib
import hmac
import urllib.parse
from datetime import datetime
import time
import ssl
import json
import websocket
import _thread

from amazon_transcribe.eventstream import EventStreamMessageSerializer
from amazon_transcribe.eventstream import EventStreamBuffer

from boto3.session import Session

# GETTING STARTED
#   pip3 install websocket-client
#   pip3 install ipython
#   pip3 install amazon_transcribe
#   Add your credentials to ACCESS_KEY_ID and SECRET_ACCESS_KEY

# open websocket debug output
# websocket.enableTrace(True)
websocket.enableTrace(False)

def sign(key, msg):
    return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()

def getSignatureKey(key, dateStamp, region, serviceName):
    kDate = sign(("AWS4" + key).encode("utf-8"), dateStamp)
    kRegion = sign(kDate, region)
    kService = sign(kRegion, serviceName)
    kSigning = sign(kService, "aws4_request")
    return kSigning

def create_pre_signed_url(region, language_code, media_encoding, sample_rate):
    # 获得access key和secret key
    credentials = Session().get_credentials()
    access_key_id = credentials.access_key
    secret_access_key = credentials.secret_key

    method = "GET"
    service = "transcribe"
    endpoint = "wss://transcribestreaming." + region + ".amazonaws.com:8443"
    host = "transcribestreaming." + region + ".amazonaws.com:8443"
    algorithm = "AWS4-HMAC-SHA256"

    t = datetime.utcnow()
    amz_date =t.strftime('%Y%m%dT%H%M%SZ')
    datestamp =t.strftime('%Y%m%d')

    canonical_uri = "/stream-transcription-websocket"

    canonical_headers = "host:" + host + "\n"
    signed_headers = "host"

    credential_scope = datestamp + "/" + region + "/" + service + "/" + "aws4_request"

    canonical_querystring = "X-Amz-Algorithm=" + algorithm
    canonical_querystring += "&X-Amz-Credential=" + urllib.parse.quote_plus(access_key_id + "/" + credential_scope)
    canonical_querystring += "&X-Amz-Date=" + amz_date
    canonical_querystring += "&X-Amz-Expires=300"
    canonical_querystring += "&X-Amz-SignedHeaders=" + signed_headers
    canonical_querystring += "&language-code="+ language_code +"&media-encoding=" + media_encoding +"&sample-rate=" + sample_rate

    # Zero length string for connecting
    payload_hash = hashlib.sha256(("").encode('utf-8')).hexdigest()

    canonical_request = method + '\n' \
                        + canonical_uri + '\n' \
                        + canonical_querystring + '\n' \
                        + canonical_headers + '\n' \
                        + signed_headers + '\n' \
                        + payload_hash

    string_to_sign = algorithm + "\n" \
                     + amz_date + "\n" \
                     + credential_scope + "\n" \
                     + hashlib.sha256(canonical_request.encode("utf-8")).hexdigest()

    signing_key = getSignatureKey(secret_access_key, datestamp, region, service)

    signature = hmac.new(signing_key, string_to_sign.encode("utf-8"),
                         hashlib.sha256).hexdigest()

    canonical_querystring += "&X-Amz-Signature=" + signature

    request_url = endpoint + canonical_uri + "?" + canonical_querystring

    return request_url

def send_data(ws):

    testFile = "xxx.pem"

    bufferSize = 1024*16
    # bufferSize = 65004

    stream_headers = {
        ":message-type": "event",
        ":event-type": "AudioEvent",
        ":content-type": "application/octet-stream",
    }

    eventstream_serializer = EventStreamMessageSerializer()

    with open(testFile, "rb") as source:
        while True:
            audio_chunk = source.read(bufferSize)
            # 将音频数据进行编码
            event_bytes = eventstream_serializer.serialize(stream_headers, audio_chunk)

            ws.send(event_bytes, opcode = 0x2) # 0 x 2 send binary

            # end with b'' data bytes
            if len(audio_chunk) == 0:
                break


def loop_receiving(ws):
    try:
        while True:
            result = ws.recv()

            if result == '':
                continue

            eventStreamBuffer = EventStreamBuffer()

            eventStreamBuffer.add_data(result)
            eventStreamMessage = eventStreamBuffer.next()

            stream_payload = eventStreamMessage.payload

            transcript = json.loads(bytes.decode(stream_payload, "UTF-8"))

            print("response:",transcript)

            results = transcript['Transcript']['Results']
            if len(results)>0:
                for length in range(len(results)):
                    if 'IsPartial' in results[length]:
                        print('IsPartial:', results[length]['IsPartial'])

                    if 'Alternatives' in results[length]:
                        alternatives = results[length]['Alternatives']
                        if len(alternatives)>0:
                            for sublength in range(len(alternatives)):
                                if 'Transcript' in alternatives[sublength]:
                                    print('Transcript:', alternatives[sublength]['Transcript'])


    except Exception as e:
        if 'WebSocketConnectionClosedException' == e.__class__.__name__:
            print("Error: websocket connection is closed")
        else:
            print(f"Exception Name: {e.__class__.__name__}")


def main():
    url = create_pre_signed_url("us-east-1", "en-US", "pcm", "16000")
    ws = websocket.create_connection(url, sslopt={"cert_reqs": ssl.CERT_NONE})

    _thread.start_new_thread(loop_receiving, (ws,))
    print("Receiving...")
    send_data(ws)

    while True:
        time.sleep(1)

main()

