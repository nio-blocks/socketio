import json
from threading import Thread
from datetime import timedelta
from ws4py.client import WebSocketBaseClient
from nio.modules.scheduler import Job


class SocketIOWebSocketClient(WebSocketBaseClient):

    def __init__(self, url, block):
        super().__init__(url, None, None)
        self._th = Thread(target=self.run, name='SocketIOWebSocketClient')
        self._block = block
        self.logger = block.logger
        self._room = block.room()
        self._listen = block.listen()
        self._restart_handler = block.handle_reconnect
        self._data_handler = block.handle_data
        self._heartbeat_expiry_job = None

    def handshake_ok(self):
        """ Called when the initial handshake succeeds.

        This method will start our client thread which will then wait
        for a successful connection to complete.
        """
        self._th.start()
        self._th.join(timeout=1.0)

    def opened(self):
        """ Called when the connection is opened """
        self.logger.info("Socket connection open")
        # Send a connection request
        self._send_packet(52)

    def closed(self, code, reason=None):
        """ Called when the connection is opened """
        self.logger.info(
            "Socket connection closed {0}:{1}".format(code, reason))
        self._restart_handler()

    def received_message(self, m):
        """ Called whenever a message is received from the server """
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

    def send_msg(self, msg):
        self._send_packet(3, '', '', msg)

    def send_dict(self, data):
        self._send_packet(4, '', '', json.dumps(data))

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

    def send_heartbeat(self):
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
        self.logger.debug("Sending heartbeat message")
        self._send_packet(2)

    def _parse_message(self, message):
        """parses a message, if it can"""
        try:
            obj = json.loads(message)
        except ValueError:
            obj = {'message': message}

        return obj

    def _recv_disconnect(self, data=None):
        self.logger.info("Disconnection detected")
        self._restart_handler()

    def _recv_connect(self, data=None):
        self.logger.info("Socket.io connection confirmed")

        self.logger.debug("Joining room %s" % self._room)
        self.send_event('ready', self._room)

        # Now that we're connected, start heartbeating
        self.start_heartbeats()

    def _heartbeat_expired(self):
        """ Called when a heartbeat request has expired """
        self.logger.error("No heartbeat response was received...reconnecting")
        self._stop_heartbeats()
        self._block.handle_reconnect()

    def start_heartbeats(self):
        """ Start a job which will periodically send heartbeats to the server.

        This method will also start a job that will wait for responses in case
        the server doesn't respond in time.
        """
        # Cancel any existing heartbeat expiry job
        if self._heartbeat_expiry_job:
            self._heartbeat_expiry_job.cancel()
        self._heartbeat_expiry_job = None

    def _stop_heartbeats(self):
        # Cancel any existing heartbeat expiry job
        if self._heartbeat_expiry_job:
            self._heartbeat_expiry_job.cancel()
        self._heartbeat_expiry_job = None

    def _recv_heartbeat(self, data=None):
        self.logger.debug("Heartbeat PONG received")
        self._stop_heartbeats()

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
