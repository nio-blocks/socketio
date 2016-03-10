import json
from datetime import timedelta
from nio.modules.scheduler import Job
from .client import SocketIOWebSocketClient


class SocketIOWebSocketClientV1(SocketIOWebSocketClient):

    """ A client for 1.0 socket.io servers """

    def __init__(self, url, block):
        super().__init__(url, block)
        self._heartbeat_expiry_job = None

    def opened(self):
        self.logger.info("Socket connection open")
        # Send a connection request
        self._send_packet(52)

    def received_message(self, m):
        # The message type comes as the first two digits
        try:
            message_type = int(str(m)[:2])
        except ValueError:
            self.logger.warning(
                "Received an improperly formatted message: %s" % m)
            return

        message_data = str(m)[2:]

        self.logger.debug("Received a message: {}".format(message_data))

        # Handle the different types
        message_handlers = {
            3: self._recv_heartbeat,
            40: self._recv_connect,
            41: self._recv_disconnect,
            42: self._recv_event
        }

        if message_type not in message_handlers:
            self.logger.warning(
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

        self.logger.debug("Sending packet: %s" % packet_text)
        try:
            self.send(packet_text)
        except:
            self.logger.exception("Error sending packet")

    def _send_heartbeat(self):
        if self._heartbeat_expiry_job:
            self.logger.warning("Trying to send a heartbeat but haven't "
                                "gotten the previous PONG yet")
        else:
            # The heartbeat job has been cancelled, let's start a new one
            # The heartbeat pong receive method will cancel this job
            self._heartbeat_expiry_job = Job(
                self._heartbeat_expired,
                timedelta(seconds=self._block._hb_timeout),
                repeatable=False)

        # Send the heartbeat regardless of whether the expiry job had
        # been cancelled yet
        super()._send_heartbeat()

    def _heartbeat_expired(self):
        """ Called when a heartbeat request has expired """
        self.logger.error("No heartbeat response was received...reconnecting")
        self._heartbeat_expiry_job = None
        self._block.handle_reconnect()

    def _recv_heartbeat(self, data=None):
        self.logger.debug("Heartbeat PONG received")
        # Cancel any existing heartbeat expiry job
        if self._heartbeat_expiry_job:
            self._heartbeat_expiry_job.cancel()
        self._heartbeat_expiry_job = None

    def _recv_event(self, data=None):
        # when we receive an event, we get a dictionary containing the event
        # name, and a list of arguments that come with it. we only care about
        # the first item in the list of arguments
        if not self._listen:
            self.logger.debug("Ignoring incoming data from web socket")
            return

        event_data = json.loads(data)
        self._data_handler({
            'event': event_data[0],
            'data': self._parse_message(event_data[1])
        })
