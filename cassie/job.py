import time
import uuid
import logging
import datetime
import threading

__version__ = '0.1'
__all__ = ['JobRun', 'JobManager']

def normalize_job_id(job_id):
	if isinstance(job_id, str):
		job_id = uuid.UUID(job_id)
	if not isinstance(job_id, uuid.UUID):
		raise Exception('invalid job id, must be uuid.UUID instance')
	return job_id

class JobRequestDelete:
	pass

class JobRun(threading.Thread):
	def __init__(self, callback, args):
		self.callback = callback
		self.callback_args = args
		self.request_delete = False
		self.exception = None
		self.reaped = False
		threading.Thread.__init__(self)

	def run(self):
		try:
			result = self.callback(*self.callback_args)
			if isinstance(result, JobRequestDelete):
				self.request_delete = True
		except Exception as error:
			self.exception = error
		return

# Job Dictionary Details:
#   last_run: datetime.datetime
#   run_every: datetime.timedelta
#   job: None or JobRun instance
#   callback: function
#   parameters: list of parameters to be passed to the callback function
#   enabled: boolean if false do not run the job
#   tolerate_exceptions: boolean if true this job will run again after a failure
#   run_count: number of times the job has been ran
#   expiration: number of times to run a job, datetime.timedelta instance or None
class JobManager(threading.Thread):
	def __init__(self, use_utc = True, logger_name = 'job_manager'):
		self.__jobs__ = {}
		self.running = threading.Event()
		self.shutdown = threading.Event()
		self.shutdown.set()
		self.job_lock = threading.RLock()
		self.use_utc = use_utc
		threading.Thread.__init__(self)
		self.logger = logging.getLogger(logger_name)

	def now(self):
		if self.use_utc:
			return datetime.datetime.utcnow()
		else:
			return datetime.datetime.now()

	def now_is_after(self, d):
		return bool(d <= self.now())

	def now_is_before(self, d):
		return bool(d >= self.now())

	def stop(self):
		self.logger.debug('stopping the job manager')
		self.running.clear()
		self.shutdown.wait()
		self.job_lock.acquire()
		self.logger.debug('waiting on all job threads')
		for job_id, job_desc in self.__jobs__.items():
			if job_desc['job'] == None:
				continue
			if not job_desc['job'].is_alive():
				continue
			job_desc['job'].join()
		self.join()
		self.job_lock.release()
		self.logger.info('the job manager has been stopped')
		return

	def run(self):
		self.logger.info('the job manager has been started')
		self.running.set()
		self.shutdown.clear()
		self.job_lock.acquire()
		while self.running.is_set():
			self.job_lock.release()
			time.sleep(1)
			self.job_lock.acquire()
			if not self.running.is_set():
				break

			# Reap Jobs
			jobs_for_removal = []
			for job_id, job_desc in self.__jobs__.items():
				if job_desc['job'].is_alive() or job_desc['job'].reaped:
					continue
				if job_desc['job'].exception != None:
					if job_desc['tolerate_exceptions'] == False:
						self.logger.error('job ' + str(job_id) + ' encountered an error and is not set to tolerate exceptions')
						jobs_for_removal.append(job_id)
					else:
						self.logger.warning('job ' + str(job_id) + ' encountered an error')
				if isinstance(job_desc['expiration'], int):
					if job_desc['expiration'] > 0:
						job_desc['expiration'] -= 1
					else:
						jobs_for_removal.append(job_id)
				elif isinstance(job_desc['expiration'], datetime.datetime):
					if self.now_is_after(job_desc['expiration']):
						jobs_for_removal.append(job_id)
				if job_desc['job'].request_delete:
					jobs_for_removal.append(job_id)
				job_desc['job'].reaped = True
			for job_id in jobs_for_removal:
				self.job_del(job_id)

			# Sow Jobs
			for job_id, job_desc in self.__jobs__.items():
				if self.now_is_before(job_desc['last_run'] + job_desc['run_every']):
					continue
				if job_desc['job'].is_alive():
					continue
				if not job_desc['job'].reaped:
					continue
				job_desc['last_run'] = self.now() # still update the timestamp
				if not job_desc['enabled']:
					continue
				job_desc['run_count'] += 1
				job_desc['job'] = JobRun(job_desc['callback'], job_desc['parameters'])
				job_desc['job'].start()
		self.job_lock.release()
		self.shutdown.set()

	def job_add(self, callback, parameters = [], hours = 0, minutes = 0, seconds = 0, tolerate_exceptions = True, expiration = None):
		job_desc = {}
		job_desc['job'] = JobRun(callback, parameters)
		job_desc['last_run'] = self.now()
		job_desc['run_every'] = datetime.timedelta(0, ((hours * 60 * 60) + (minutes * 60) + seconds))
		job_desc['callback'] = callback
		job_desc['parameters'] = parameters
		job_desc['enabled'] = True
		job_desc['tolerate_exceptions'] = tolerate_exceptions
		job_desc['run_count'] = 0
		if isinstance(expiration, int):
			job_desc['expiration'] = expiration
		elif isinstance(expiration, datetime.timedelta):
			job_desc['expiration'] = self.now() + expiration
		elif isinstance(expiration, datetime.datetime):
			job_desc['expiration'] = expiration
		else:
			job_desc['expiration'] = None
		job_id = uuid.uuid4()
		with self.job_lock:
			self.__jobs__[job_id] = job_desc
		self.logger.info('added a new job with id: ' + str(job_id))
		return job_id

	def job_count(self):
		return len(self.__jobs__)

	def job_count_enabled(self):
		return len(filter(lambda job_desc: job_desc['enabled'], self.__jobs__.values()))

	def job_enable(self, job_id):
		job_id = normalize_job_id(job_id)
		with self.job_lock:
			job_desc = self.__jobs__[job_id]
			job_desc['enabled'] = True

	def job_disable(self, job_id):
		job_id = normalize_job_id(job_id)
		with self.job_lock:
			job_desc = self.__jobs__[job_id]
			job_desc['enabled'] = False

	def job_del(self, job_id):
		job_id = normalize_job_id(job_id)
		self.logger.info('deleting job with id: ' + str(job_id))
		with self.job_lock:
			del self.__jobs__[job_id]

	def job_exists(self, job_id):
		job_id = normalize_job_id(job_id)
		if job_id in self.__jobs__:
			return True
		else:
			return False
