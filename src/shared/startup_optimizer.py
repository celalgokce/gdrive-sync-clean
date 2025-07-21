import time
import logging
import asyncio
from typing import List, Callable, Dict, Any
from concurrent.futures import ThreadPoolExecutor
import threading

logger = logging.getLogger(__name__)

class StartupOptimizer:
    """12-Factor compliant fast startup optimizer"""
    
    def __init__(self, max_workers: int = 4):
        self.max_workers = max_workers
        self.startup_tasks: List[Dict[str, Any]] = []
        self.startup_metrics = {}
        
    def add_startup_task(self, 
                        name: str, 
                        func: Callable, 
                        args: tuple = (), 
                        kwargs: dict = None,
                        critical: bool = True,
                        timeout: int = 30):
        """Add a task to run during startup"""
        if kwargs is None:
            kwargs = {}
            
        self.startup_tasks.append({
            'name': name,
            'func': func,
            'args': args,
            'kwargs': kwargs,
            'critical': critical,
            'timeout': timeout
        })
        
        logger.debug(f"Added startup task: {name} (critical: {critical})")
    
    def run_startup_sequence(self) -> bool:
        """Run all startup tasks with optimization"""
        start_time = time.time()
        logger.info(f"Starting optimized startup sequence with {len(self.startup_tasks)} tasks")
        
        # Separate critical and non-critical tasks
        critical_tasks = [task for task in self.startup_tasks if task['critical']]
        non_critical_tasks = [task for task in self.startup_tasks if not task['critical']]
        
        # Run critical tasks first (sequential)
        logger.info(f"Running {len(critical_tasks)} critical tasks...")
        if not self._run_tasks_sequential(critical_tasks):
            logger.error("Critical startup tasks failed")
            return False
        
        # Run non-critical tasks in parallel
        if non_critical_tasks:
            logger.info(f"Running {len(non_critical_tasks)} non-critical tasks in parallel...")
            self._run_tasks_parallel(non_critical_tasks)
        
        total_time = time.time() - start_time
        self.startup_metrics['total_time'] = total_time
        self.startup_metrics['task_count'] = len(self.startup_tasks)
        
        logger.info(f"Startup sequence completed in {total_time:.2f}s")
        return True
    
    def _run_tasks_sequential(self, tasks: List[Dict[str, Any]]) -> bool:
        """Run tasks sequentially"""
        for task in tasks:
            start_time = time.time()
            try:
                logger.debug(f"Running critical task: {task['name']}")
                result = task['func'](*task['args'], **task['kwargs'])
                
                execution_time = time.time() - start_time
                self.startup_metrics[task['name']] = {
                    'execution_time': execution_time,
                    'status': 'success',
                    'result': str(result)[:100]  # Truncate long results
                }
                
                logger.debug(f"Task {task['name']} completed in {execution_time:.2f}s")
                
            except Exception as e:
                execution_time = time.time() - start_time
                self.startup_metrics[task['name']] = {
                    'execution_time': execution_time,
                    'status': 'failed',
                    'error': str(e)
                }
                
                logger.error(f"Critical task {task['name']} failed: {e}")
                return False
        
        return True
    
    def _run_tasks_parallel(self, tasks: List[Dict[str, Any]]):
        """Run tasks in parallel"""
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = {}
            
            # Submit all tasks
            for task in tasks:
                future = executor.submit(self._run_single_task, task)
                futures[future] = task
            
            # Wait for completion
            for future in futures:
                task = futures[future]
                try:
                    future.result(timeout=task['timeout'])
                except Exception as e:
                    logger.warning(f"Non-critical task {task['name']} failed: {e}")
    
    def _run_single_task(self, task: Dict[str, Any]):
        """Run a single task with metrics"""
        start_time = time.time()
        try:
            logger.debug(f"Running non-critical task: {task['name']}")
            result = task['func'](*task['args'], **task['kwargs'])
            
            execution_time = time.time() - start_time
            self.startup_metrics[task['name']] = {
                'execution_time': execution_time,
                'status': 'success',
                'result': str(result)[:100]
            }
            
            logger.debug(f"Task {task['name']} completed in {execution_time:.2f}s")
            return result
            
        except Exception as e:
            execution_time = time.time() - start_time
            self.startup_metrics[task['name']] = {
                'execution_time': execution_time,
                'status': 'failed',
                'error': str(e)
            }
            raise
    
    def get_startup_metrics(self) -> Dict[str, Any]:
        """Get startup performance metrics"""
        return self.startup_metrics
