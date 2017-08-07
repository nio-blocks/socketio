from time import sleep
from unittest.mock import MagicMock

from nio.testing import NIOTestCase

from ..client.heartbeats import HeartbeatHandler


class TestClient(NIOTestCase):

    def test_heartbeats(self):
        """ Test that our heartbeat handler functions properly.

        This test contains sleeps.
        """

        # How often to send heartbeats
        heartbeat_interval = 0.2

        # How long to wait for a response
        heartbeat_timeout = heartbeat_interval * 2.5

        # How much time to wait after an expected action should have occurred.
        # Make this delta small to make the test run faster, make it large to
        # prevent race conditions.
        timeout_delta = 0.2

        heartbeat_sender_cb = MagicMock()
        heartbeat_timeout_cb = MagicMock()
        hb_handler = HeartbeatHandler(
            send_callback=heartbeat_sender_cb,
            timeout_callback=heartbeat_timeout_cb,
            heartbeat_interval=heartbeat_interval,
            heartbeat_timeout=heartbeat_timeout,
            logger=MagicMock())

        # Shouldn't send heartbeats until told to do so
        sleep(heartbeat_interval + timeout_delta)
        heartbeat_sender_cb.assert_not_called()

        # Start sending heartbeats, make sure we send one after the interval
        hb_handler.start_heartbeats()
        sleep(heartbeat_interval + timeout_delta)
        self.assertGreater(heartbeat_sender_cb.call_count, 0)

        # Process a response, but then don't process one for a while
        # We should get a timeout and the callback should be called
        hb_handler.handle_heartbeat_response()
        sleep(heartbeat_timeout + timeout_delta)
        self.assertGreater(heartbeat_timeout_cb.call_count, 0)

        # Tell the heartbeat handler to stop processing heartbeats
        hb_handler.stop_heartbeats()
        self.assertIsNone(hb_handler._heartbeat_job)
        self.assertIsNone(hb_handler._heartbeat_expiry_job)
