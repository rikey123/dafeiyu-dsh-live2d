"""Use native protobuf/audio framing without logging private transport payloads."""
import json

from pipecat.frames.frames import InputTransportMessageFrame
from pipecat.frames.protobufs import frames_pb2
from pipecat.serializers.protobuf import ProtobufFrameSerializer


class PrivateTransportFrame(InputTransportMessageFrame):
    def __str__(self):
        return f'{self.name}(message: [private])'

    def __repr__(self):
        return str(self)


class VoiceProtobufSerializer(ProtobufFrameSerializer):
    async def deserialize(self, data):
        # Upstream's message branch logs the entire dict at DEBUG, including
        # screenshot base64. Decode only that branch here; all audio, text and
        # outbound serialization stay owned by the maintained native serializer.
        try:
            proto = frames_pb2.Frame.FromString(data)
            if proto.WhichOneof('frame') != 'message':
                return await super().deserialize(data)
            message = json.loads(proto.message.data)
            if not isinstance(message, dict):
                return None
            return PrivateTransportFrame(message=message)
        except (ValueError, TypeError, UnicodeError):
            return None
        except Exception:
            # Protobuf DecodeError can vary with the installed protobuf runtime.
            # Never include a decoding exception's private input in diagnostics.
            return None
