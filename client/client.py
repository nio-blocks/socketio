from threading import Thread
from ws4py.client import WebSocketBaseClient
from .heartbeats import HeartbeatHandler
from .sender import PacketSender
from .receiver import PacketReceiver


class SocketIOWebSocketClient(WebSocketBaseClient):

    def __init__(self, url, room, connect_event, heartbeat_interval,
                 heartbeat_timeout, data_callback,
                 disconnect_callback, logger):
        super().__init__(url, None, None)

        # A thread to run the client in
        self._th = Thread(target=self.run, name='SocketIOWebSocketClient')

        # A packet sender that will send data to the socket
        self.sender = PacketSender(
            client=self,
            logger=logger)

        # A heartbeat handler to deal with sending/receiving heartbeats
        self._heartbeats = HeartbeatHandler(
            send_callback=self.sender.send_heartbeat,
            timeout_callback=disconnect_callback,
            heartbeat_interval=heartbeat_interval,
            heartbeat_timeout=heartbeat_timeout,
            logger=logger)

        # A packet receiver that will receive data from the socket
        self.receiver = PacketReceiver(
            client=self,
            logger=logger)

        self.logger = logger
        self._connect_event = connect_event
        self._room = room
        self._listen = data_callback
        self._disconnect_handler = disconnect_callback
        self._data_handler = data_callback

    def handshake_ok(self):
        """ Called when the initial handshake succeeds.

        This method will start our client thread which will then wait
        for a successful connection to complete.
        """
        self.logger.info("Handshake successful")
        self._th.start()
        self._th.join(timeout=1.0)

    def opened(self):
        """ Called when the connection is opened """
        self.logger.info("Socket connection open")
        # Send a connection request
        self.sender.send_packet(52)

    def close(self, *args, **kwargs):
        # Stop all of our heartbeats before closing
        self._heartbeats.stop_heartbeats()
        super().close(*args, **kwargs)

    def closed(self, code, reason=None):
        """ Called when the connection is closed """
        self.logger.info(
            "Socket connection closed {0}:{1}".format(code, reason))
        self._heartbeats.stop_heartbeats()
        self._disconnect_handler()

    def received_message(self, m):
        """ Called whenever a message is received from the server """
        self.receiver.handle_message(m)
