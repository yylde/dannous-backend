
import os
import sys
import unittest
import threading

# Add src to path
sys.path.append(os.path.join(os.getcwd(), 'src'))

from src.ollama_queue import OllamaQueueManager

class TestQueueManager(unittest.TestCase):
    def setUp(self):
        # Reset singleton if it exists
        if OllamaQueueManager._instance:
            OllamaQueueManager._instance.shutdown(wait=False)
            OllamaQueueManager._instance = None
            
    def tearDown(self):
        if OllamaQueueManager._instance:
            OllamaQueueManager._instance.shutdown(wait=False)
            OllamaQueueManager._instance = None

    def test_worker_count(self):
        # Initialize queue manager
        qm = OllamaQueueManager()
        
        # Check number of workers
        print(f"Worker count: {qm._num_workers}")
        self.assertEqual(qm._num_workers, 10)
        
        # Check actual threads
        active_threads = [t.name for t in threading.enumerate() if "OllamaWorker" in t.name]
        print(f"Active worker threads: {len(active_threads)}")
        # Note: Thread starting might be async or take a moment, but _num_workers should be set immediately
        
        # Clean up
        qm.shutdown(wait=False)

if __name__ == '__main__':
    unittest.main()
