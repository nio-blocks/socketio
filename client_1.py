import json
from .client import SocketIOWebSocketClient


class SocketIOWebSocketClientV1(SocketIOWebSocketClient):

    """ A client for 1.0 socket.io servers """

    def opened(self):
        self._logger.info("Socket connection open")
        # Send a connection request
        self._send_packet(52)

    def received_message(self, m):
        # The message type comes as the first two digits
        try:
            message_type = int(str(m)[:2])
        except ValueError:
            self._logger.warning(
                "Received an improperly formatted message: %s" % m)
            return

        message_data = str(m)[2:]

        self._logger.debug("Received a message: {}".format(message_data))

        # Handle the different types
        message_handlers = {
            3: self._recv_heartbeat,
            40: self._recv_connect,
            41: self._recv_disconnect,
            42: self._recv_event
        }

        if message_type not in message_handlers:
            self._logger.warning(
                "Message type %s is not a valid message type" % message_type)
            return

        message_handlers[message_type](message_data)

    def send_event(self, event, data):
        self._send_packet(42, event, data)

    def _send_packet(self, code, path='', data='', id=''):
        if path or data:
            packet_text = "{}{}".format(code, json.dumps([path, data]))
        else:
            packet_text = "{}".format(code)

        self._logger.debug("Sending packet: %s" % packet_text)
        try:
            self.send(packet_text)
        except Exception as e:
            self._logger.error(
                "Error sending packet: {0}: {1}".format(type(e).__name__,
                                                        str(e))
            )

    def _recv_heartbeat(self, data=None):
        self._logger.debug("Heartbeat PONG received")

    def _recv_event(self, data=None):
        # when we receive an event, we get a dictionary containing the event
        # name, and a list of arguments that come with it. we only care about
        # the first item in the list of arguments
        if not self._listen:
            self._logger.debug("Ignoring incoming data from web socket")
            return

        event_data = json.loads(data)
        self._data_handler({
            'event': event_data[0],
            'data': self._parse_message(event_data[1])
        })
