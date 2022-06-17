from turtle import bye
from pexpect import TIMEOUT
import socketio
import asyncio
import string
import random
from aiortc.contrib.media import MediaPlayer, MediaRecorder
from aiortc import RTCPeerConnection, RTCSessionDescription
import json

SERVER_URL = "https://192.168.1.18:443"
VIDEO_SIZE = "320x240"
QUEUE_FIRST_ELEMENT = 0
TIMEOUT_VALUE = 30
EXIT_TIMEOUT_VALUE = TIMEOUT_VALUE*4

# Generate random String : https://stackoverflow.com/questions/2823316/generate-a-random-letter-in-python
def random_name():
    name = ''
    for i in range(5):
        name += random.choice(string.ascii_letters)
    return name
    
# Creation queue : https://docs.python.org/3/library/asyncio-queue.html
def asyncio_queue_creation(sio, type_messages):
    queue = asyncio.Queue()
    for msg in type_messages:
        sio.on(msg, lambda content='', msg=msg:queue.put_nowait((msg, content)))
    return queue
        
async def main():
    while True :
        # SocketIo: https://python-socketio.readthedocs.io/en/latest/client.html#creating-a-client-instance
        # SSL parameter used from laboratory instruction
        sio = socketio.AsyncClient(ssl_verify=False)
        type_messages = ['created', 'joined', 'full', "new_peer", "invite", "bye"]
        asyncioQueue = asyncio_queue_creation(sio, type_messages)

        # 1. Wait until keypress (to be replaced later by the pushbutton press event).
        # input key : https://stackoverflow.com/questions/983354/how-to-make-a-python-script-wait-for-a-pressed-key
        input("Press ENTER to ring")

        # 2. Connect to the signaling server (server address is from constant variable)
        # Connecting to a Server : https://python-socketio.readthedocs.io/en/latest/client.html#creating-a-client-instance
        await sio.connect(SERVER_URL)

        # 3. Join a conference room with a random name (send 'create' signal with room name).
        roomName = random_name()
        # Ne fonctionne pas avec "create", le serveur comprend le message "join" pour créer une salle (?)
        await sio.emit("join", roomName)

        # 4. Wait for response. If response is 'joined' or 'full', stop processing and return to the loop. Go on if response is 'created'.
        # asyncio.wait_for documentation : https://docs.python.org/3/library/asyncio-task.html
        response = await asyncio.wait_for(asyncioQueue.get(), None)

        if(response[QUEUE_FIRST_ELEMENT] == "joined" or response[QUEUE_FIRST_ELEMENT] == "full"):
            print("ERROR : Wrong message (created required)")
            continue
        if(response[QUEUE_FIRST_ELEMENT] != "created"):
            print("ERROR : Wrong message (created required)")
            continue

        # 5. Send a message (SMS, Telegram, email, ...) to the user with the room name. Or simply start by printing it on the terminal. 
        print("Doorbell is ringing, please join : ", roomName)

        # 6. Wait (with timeout) for a 'new_peer' message. If timeout, send 'bye' to signaling server and return to the loop. 
        # Need to catch exception because asyncio.wait_for raises TimeoutError exception in case of timeout
        # TimeoutError exception : https://docs.python.org/3/library/asyncio-exceptions.html#asyncio.TimeoutError
        try:
            response = await asyncio.wait_for(asyncioQueue.get(), TIMEOUT_VALUE) 
            if(response[QUEUE_FIRST_ELEMENT] == "new_peer"):
                print("A new peer is arrived")  
            else:
                print("ERROR : Wrong message (new_peer required)")
                continue
        except asyncio.TimeoutError:
            print("Timeout ERROR : new_peer")
            sio.emit("bye", roomName)
            continue

        # 7. Wait (with timeout) for an 'invite' message. If timemout, send 'bye' to signaling server and return to the loop. 
        try:
            response = await asyncio.wait_for(asyncioQueue.get(), TIMEOUT_VALUE) 
            if(response[QUEUE_FIRST_ELEMENT] == "invite"):
                print("An invite message is arrived")    
            else:
                print("ERROR : Wrong message (invite required)")
                continue      
        except asyncio.TimeoutError:
            print("Timeout ERROR : invite")
            sio.emit("bye", roomName)
            continue

        # 8. Acquire the media stream from the Webcam.
        # MediaPlayer and MediaRecorder : https://aiortc.readthedocs.io/en/latest/helpers.html
        # Create MediaPlayer for video stream
        videoPlayer = MediaPlayer('/dev/video0', format='v4l2', options={'video_size': VIDEO_SIZE})
        # Create MediaPlayer for audio stream
        audioPlayer = MediaPlayer('default', format='pulse')

        # 9. Create the PeerConnection and add the streams from the local Webcam.
        # RTCPeerConnection for aiortc : https://aiortc.readthedocs.io/en/latest/api.html#webrtc
        pc = RTCPeerConnection()
        pc.addTrack(videoPlayer.video)
        
        # INFO : L'ajout du mediaPlayer audio à la RTCPeerConnection fait crasher le programme lors du pc.setRemoteDescritpion(sdp)
        # -> pc.addTrack(audioPlayer.audio)

        # 10. Add the SDP from the 'invite' to the peer connection.
        # Get SDP : https://stackoverflow.com/questions/69372082/how-to-set-an-answer-as-localdescription-in-aiortc-python
        offer = response[1]
        sdp = RTCSessionDescription(sdp = offer['sdp'], type = offer['type'])
        #Register SDP
        await pc.setRemoteDescription(sdp)

        # 11. Generate the local session description (answer) and send it as 'ok' to the signaling server.
        answer = await pc.createAnswer()
        await pc.setLocalDescription(answer)
        # Re-read the answer for ICE candidates (from laboratory instruction)
        answer = pc.localDescription
        await sio.emit("ok", {"sdp":answer.sdp, "type":answer.type})

        # Add MediaRecorder
        # on_track function : https://github.com/aiortc/aiortc/blob/main/examples/videostream-cli/cli.py
        audioRecorder = MediaRecorder("default", format="alsa")
        @pc.on("track")
        def on_track(track):
            audioRecorder.addTrack(track)
            audioRecorder.start()

        # 12. Wait (with timeout) for a 'bye' message. 
        try:
            response = await asyncio.wait_for(asyncioQueue.get(), EXIT_TIMEOUT_VALUE) 
            if(response[QUEUE_FIRST_ELEMENT] == "bye"):
                print("A bye message is arrived")      

                # 13. Send a 'bye' message back and clean everything up (peerconnection, media, signaling). 
                await sio.emit("bye", roomName)
                # Stop mediaPlayer (in JS but similare syntaxe for stop function in Py) : https://stackoverflow.com/questions/21497566/webrtc-video-stream-stop-sharing
                # Delete object in python : https://www.programiz.com/python-programming/del
                videoPlayer.video.stop()
                del videoPlayer
                audioPlayer.audio.stop()
                del audioPlayer
                await audioRecorder.stop()
                await pc.close()
                # Disconnect sio : https://python-socketio.readthedocs.io/en/latest/client.html#catch-all-event-handlers
                await sio.disconnect()
        except asyncio.TimeoutError:
            print("Timeout ERROR : bye")
            sio.emit("bye", roomName)
            continue

# Lancement du programme
asyncio.run(main())
