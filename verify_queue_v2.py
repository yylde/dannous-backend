
import os
import sys
import unittest
import threading
import time

# Add src to path
sys.path.append(os.path.join(os.getcwd(), 'src'))

from src.queue_manager_v2 import QueueManagerV2
from src.config import settings

class TestQueueManagerV2(unittest.TestCase):
    def setUp(self):
        # Reset singleton if it exists
        if QueueManagerV2._instance:
            QueueManagerV2._instance.shutdown()
            QueueManagerV2._instance = None
            
    def tearDown(self):
        if QueueManagerV2._instance:
            QueueManagerV2._instance.shutdown()
            QueueManagerV2._instance = None

    def test_worker_count(self):
        # Ensure setting is correct
        print(f"Configured worker count: {settings.queue_worker_count}")
        self.assertEqual(settings.queue_worker_count, 10)
        
        # Initialize queue manager
        qm = QueueManagerV2()
        qm.start()
        
        # Allow threads to start
        time.sleep(1)
        
        # Check internal list
        print(f"Internal worker threads: {len(qm._worker_threads)}")
        self.assertEqual(len(qm._worker_threads), 10)
        
        # Check actual threads
        active_threads = [t.name for t in threading.enumerate() if "QueueWorker-" in t.name]
        print(f"Active worker threads: {len(active_threads)}")
        self.assertEqual(len(active_threads), 10)
        
        # Clean up
        qm.shutdown()

if __name__ == '__main__':
    unittest.main()
