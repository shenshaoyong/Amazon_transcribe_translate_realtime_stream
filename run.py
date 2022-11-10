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
import numpy as np
import sounddevice as sd

import pyaudio
import wave
import boto3

from amazon_transcribe.eventstream import EventStreamMessageSerializer
from amazon_transcribe.eventstream import EventStreamBuffer

from boto3.session import Session
region = "us-east-1"

translate = boto3.client(service_name='translate', region_name=region, use_ssl=True)



# GETTING STARTED
#   pip3 install websocket-client
#   pip3 install ipython
#   pip3 install amazon_transcribe
#   Add your credentials to ACCESS_KEY_ID and SECRET_ACCESS_KEY

# open websocket debug output
# websocket.enableTrace(True)
websocket.enableTrace(False)

FORMAT = pyaudio.paInt16

# if you don't know your microphone on which channel, can uncommet next line to print the list.
#print(sd.query_devices()) 
CHANNELS = 1 
RATE = 16000
CHUNK = 1024
RECORD_SECONDS = 5

audio = pyaudio.PyAudio()
     
# start Recording
source = audio.open(format=FORMAT, channels=CHANNELS,
                rate=RATE, input=True,
                frames_per_buffer=CHUNK)
print("recording...")

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

    testFile = "file.pcm"

    bufferSize = 1024*16
    # bufferSize = 65004

    stream_headers = {
        ":message-type": "event",
        ":event-type": "AudioEvent",
        ":content-type": "application/octet-stream",
    }

    eventstream_serializer = EventStreamMessageSerializer()

    #with open(testFile, "rb") as source:
    while True:
        #audio_chunk = source.read(bufferSize)
        audio_chunk = source.read(CHUNK,exception_on_overflow = False)
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

            #print("response:",transcript)

            results = transcript['Transcript']['Results']
            if len(results)>0:
                for length in range(len(results)):
                    if 'IsPartial' in results[length]:
                        print('IsPartial:', results[length]['IsPartial'])

                    if 'Alternatives' in results[length]:
                        alternatives = results[length]['Alternatives']
                        if len(alternatives)>0:
                            #for sublength in range(len(alternatives)):
                            sublength = 0
                            if 'Transcript' in alternatives[sublength]:
                                transcript = alternatives[sublength]['Transcript']
                                print(f'Transcript-中文:{transcript}' )
                                translatedText = translate.translate_text(Text=transcript, SourceLanguageCode="zh", TargetLanguageCode="en").get("TranslatedText")
                                print(f'Transcript-English:{translatedText}')


    except Exception as e:
        if 'WebSocketConnectionClosedException' == e.__class__.__name__:
            print("Error: websocket connection is closed")
        else:
            print(f"Exception Name: {e.__class__.__name__}")


def audio_callback(indata, frames, time, status):
       volume_norm = np.linalg.norm(indata) * 10
       print("|" * int(volume_norm))

def microphone():

    duration = 10 #in seconds

    stream = sd.InputStream(callback=audio_callback)
    with stream:
       sd.sleep(duration * 1000)

def main():
    url = create_pre_signed_url(region, "zh-CN", "pcm", "16000")
    print(f"url:{url}")
    ws = websocket.create_connection(url, sslopt={"cert_reqs": ssl.CERT_NONE})

    _thread.start_new_thread(loop_receiving, (ws,))
    print("Receiving...")

    send_data(ws)
    print("finished recording")
 
 
    # stop Recording
    source.stop_stream()
    stream.close()
    audio.terminate()
 

    while True:
        time.sleep(1)

#microphone()
main()

