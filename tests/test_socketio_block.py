from unittest.mock import MagicMock, patch
from threading import Event

from nio import Signal
from nio.block.terminals import DEFAULT_TERMINAL
from nio.testing import NIOBlockTestCase
from nio.util.runner import RunnerStatus

from ..socketio_block import SocketIO, SocketIOWebSocketClient


class TestSocketIOBlock(NIOBlockTestCase):

    def test_configure_creates_and_connects(self):
        """ Test that we create and connect to a client when configuring """
        blk = SocketIO()
        blk._do_handshake = MagicMock()

        client_class = "{}.{}".format(
            blk.__module__, 'SocketIOWebSocketClient')
        with patch(client_class) as mock_client,\
                patch.object(Event, 'wait') as mock_event_wait:
            # Simulate the connection event returning in time
            mock_event_wait.return_value = True
            blk._sid = "samplesid"
            self.configure_block(blk, {
                "host": "samplehost",
                "port": 1234,
                "room": "myroom",
                "listen": True
            })
            client_creation_kwargs = mock_client.call_args[1]
            self.assertEqual(
                client_creation_kwargs["url"],
                "ws://samplehost:1234/socket.io/" +
                "?transport=websocket&sid=samplesid")
            self.assertEqual(
                client_creation_kwargs["room"], "myroom")
            # Since we want to listen, our data callback should be the block's
            # handle_data method
            self.assertEqual(
                client_creation_kwargs["data_callback"], blk.handle_data)
            self.assertTrue(blk._client_ready)

    def test_configure_creates_and_connects_no_listen(self):
        """ Test that we create and connect to a client without listening """
        blk = SocketIO()
        blk._do_handshake = MagicMock()

        client_class = "{}.{}".format(
            blk.__module__, 'SocketIOWebSocketClient')
        with patch(client_class) as mock_client, \
                patch.object(Event, 'wait') as mock_event_wait:
            # Simulate the connection event returning in time
            mock_event_wait.return_value = True
            blk._sid = "samplesid"
            self.configure_block(blk, {
                "host": "samplehost",
                "port": 1234,
                "room": "myroom",
                "listen": False
            })
            client_creation_kwargs = mock_client.call_args[1]
            self.assertEqual(
                client_creation_kwargs["url"],
                "ws://samplehost:1234/socket.io/" +
                "?transport=websocket&sid=samplesid")
            self.assertEqual(
                client_creation_kwargs["room"], "myroom")
            # Since we don't want to listne, our data callback should be None
            self.assertIsNone(client_creation_kwargs["data_callback"])
            self.assertTrue(blk._client_ready)

    def test_handshake(self):
        """ Test that the block performs a handshake properly """
        blk = SocketIO()
        # Don't actually connect
        blk._connect_to_socket = MagicMock()
        self.configure_block(blk, {
            "host": "samplehost",
            "port": 1234
        })
        with patch("requests.get") as mock_request:
            mock_request.return_value.status_code = 200
            # Sample response text from socket.io
            mock_request.return_value.text = '\0xxxx {"sid":"mysid", ' + \
                '"upgrades":["websocket","polling"], "pingInterval":5000, ' + \
                '"pingTimeout":30000}'
            blk._do_handshake()

            # Test the block made the correct socket.io handshake request
            mock_request.assert_called_once_with(
                "http://samplehost:1234/socket.io/?transport=polling")

            # Make sure the block parsed the response string properly
            self.assertEqual(blk._sid, "mysid")
            self.assertEqual(blk._hb_interval, 5)
            self.assertEqual(blk._hb_timeout, 30)
            self.assertEqual(blk._transports, ["websocket", "polling"])

    def test_configure_timeout(self):
        """ Test that we clean up and raise exception if we don't connect """
        blk = SocketIO()
        blk._do_handshake = MagicMock()
        blk._close_client = MagicMock()

        client_class = "{}.{}".format(
            blk.__module__, 'SocketIOWebSocketClient')
        with patch(client_class),\
                patch.object(Event, 'wait') as mock_event_wait:
            # Simulate the connection event timing out
            mock_event_wait.return_value = False
            with self.assertRaises(Exception):
                self.configure_block(blk, {
                    "host": "samplehost",
                    "port": 1234,
                    "room": "myroom",
                    "listen": False
                })
            blk._close_client.assert_called_once_with()
            self.assertFalse(blk._client_ready)

    def test_connection_sequence(self):
        """ Test that the block opens/closes the client at the right time"""
        blk = SocketIO()
        # Don't do handshakes or create the client
        blk._do_handshake = MagicMock()

        with patch.object(SocketIOWebSocketClient, 'connect') as mock_conn, \
                patch.object(SocketIOWebSocketClient, 'close') as mock_close, \
                patch.object(Event, 'wait') as mock_wait:
            # Simulate the connection event happening properly and in time
            mock_wait.return_value = True

            # The client should be ready and connected after configuring
            self.configure_block(blk, {
                "content": "{{ $attr }}"
            })
            self.assertEqual(mock_conn.call_count, 1)
            self.assertTrue(blk._client_ready)

            # Starting the block shouldn't call connect again but we should
            # still be ready
            blk.start()
            self.assertEqual(mock_conn.call_count, 1)
            self.assertTrue(blk._client_ready)

            # Let's simulate a reconnection happening
            # We should have a close call and another connect call
            blk.handle_disconnect()
            self.assertEqual(mock_close.call_count, 1)
            self.assertEqual(mock_conn.call_count, 2)
            self.assertTrue(blk._client_ready)

            # Stopping the block should make another close call and make
            # us not ready
            blk.stop()
            self.assertEqual(mock_close.call_count, 2)
            self.assertFalse(blk._client_ready)

    def test_block_error_status(self):
        """ Test that the block goes into error status if it can't connect """
        blk = SocketIO()
        # Don't do handshakes or create the client
        blk._do_handshake = MagicMock()

        with patch.object(SocketIOWebSocketClient, 'connect') as mock_conn, \
                patch.object(Event, 'wait') as mock_wait:
            # Simulate the connection event happening properly and in time
            mock_wait.return_value = True

            # Configure the block to retry twice then give up
            self.configure_block(blk, {
                "content": "{{ $attr }}",
                "retry_options": {
                    "max_retry": 2,
                    "multiplier": 0.005  # retry quickly
                }
            })
            # The block will still connect on configure, we want to test
            # that it disconnects and gives up after it is running
            self.assertEqual(mock_conn.call_count, 1)
            self.assertTrue(blk._client_ready)

            # Our reconnections will raise ConnectionError
            blk.reconnect_client = MagicMock(side_effect=ConnectionError())
            # Let's simulate a reconnection happening
            blk.handle_disconnect()

            # We should have seen 3 calls to our connection method, one
            # original call and 2 retries
            self.assertEqual(blk.reconnect_client.call_count, 3)
            # Additionally, we should have notified 1 management signal
            # and put our block into error when we gave up retrying
            self.assert_block_status(blk, RunnerStatus.error)
            self.assert_num_mgmt_signals_notified(1)

    def test_sends_data(self):
        """ Test that the block sends incoming signals to the client """
        blk = SocketIO()
        # Don't actually connect
        blk._connect_to_socket = MagicMock()
        self.configure_block(blk, {
            "content": "{{ $attr }}"
        })
        # We'll use our own client and pretend that it's ready
        blk._client = MagicMock()
        blk._client_ready = True

        blk.process_signals([Signal({"attr": "val"})])
        # We will send a "pub" event with the result of the evaluation
        # of the content our block was configured with
        blk._client.sender.send_event.assert_called_once_with("pub", "val")

    def test_doesnt_send_when_not_connected(self):
        """ Test that the block doesn't send if it's not connected """
        blk = SocketIO()
        # Don't actually connect
        blk._connect_to_socket = MagicMock()
        self.configure_block(blk, {
            "content": "{{ $attr }}"
        })
        # We'll use our own client and pretend that it's not ready
        blk._client = MagicMock()
        blk._client_ready = False
        blk.process_signals([Signal({"attr": "val"})])
        # It shouldn't be called because we said the client wasn't ready
        blk._client.sender.send_event.assert_not_called()

    def test_doesnt_send_bad_data(self):
        """ Test that the block doesn't send anything that it can't eval """
        blk = SocketIO()
        # Don't actually connect
        blk._connect_to_socket = MagicMock()
        self.configure_block(blk, {
            "content": "{{ $attr }}"
        })
        # We'll use our own client and pretend that it's ready
        blk._client = MagicMock()
        blk._client_ready = True

        # This time, use a bad attribute that the block won't look for
        blk.process_signals([Signal({"a bad attribute": "val"})])
        # We will send a "pub" event with the result of the evaluation
        # of the content our block was configured with
        blk._client.sender.send_event.assert_not_called()

    def test_receives_data(self):
        """ Test that our block can receive socket data and notify it """
        blk = SocketIO()
        # Don't actually connect
        blk._connect_to_socket = MagicMock()
        self.configure_block(blk, {
            "listen": True
        })
        blk.start()
        # Simulate the client sending us some data
        blk.handle_data({
            "event": "recvData",  # the server uses the recvData event type
            "data": {
                "attr1": "val1"
            }
        })
        self.assert_num_signals_notified(1)
        last_sig = self.last_notified[DEFAULT_TERMINAL][-1]
        self.assertEqual(last_sig.attr1, "val1")

    def test_receives_bad_data(self):
        """ Test that we don't notify data we can't parse """
        blk = SocketIO()
        # Don't actually connect
        blk._connect_to_socket = MagicMock()
        self.configure_block(blk, {
            "listen": True
        })
        blk.start()
        # Simulate the client sending us some unparseable data
        blk.handle_data({
            "event": "recvData",  # the server uses the recvData event type
            "data": "can't make me a signal!"
        })
        # Simulate the client sending us an unknown event
        blk.handle_data({
            "event": "what am I?",  # this is not the correct event type
            "data": {}
        })
        self.assert_num_signals_notified(0)

    def get_logging_config(self):
        """ Let's use INFO log level """
        parent_log = super().get_logging_config()
        parent_log['handlers']['default']['level'] = 'INFO'
        return parent_log

    def test_host_name_spaces(self):
        """ Test that an error isn't thrown when there is a space after the
        hostname.
        """

        blk = SocketIO()
        blk._do_handshake = MagicMock()
        blk._close_client = MagicMock()

        # this will raise a socket.gaierror if the hostname has a space at the
        # end/ an invalid host is passed to socket.getaddrinfo(). If the block
        # is given a valid hostname, it will throw a ConnectionRefusedError
        # on this test.

        # mock connection
        # set return value to be ConnectionRefusedError
        client_class = "{}.{}".format(
            blk.__module__, 'SocketIOWebSocketClient')
        with patch(client_class) as mock_client:
            mock_client.return_value.connect.side_effect = \
                ConnectionRefusedError
            with self.assertRaises(ConnectionRefusedError):
                self.configure_block(blk, {
                    "host": "127.0.0.1 ",
                    "port": 80,
                    "room": "myroom",
                    "listen": True,
                    "start_without_server": False,
                })
        self.assertFalse(blk._client_ready)
