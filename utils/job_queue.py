from utils.config import config
from utils.logging_setup import get_logger
from utils.time_estimator import TimeEstimator
from utils.translations import I18N

_ = I18N._

logger = get_logger("job_queue")

class JobQueue:
    JOB_QUEUE_SD_RUNS_KEY = "Stable Diffusion Runs"
    JOB_QUEUE_PRESETS_KEY = "Preset Schedules"

    def __init__(self, name="JobQueue", max_size=50):
        self.name = name
        self.max_size = max_size
        self.pending_jobs = []
        self.job_running = False

    def has_pending(self):
        return self.job_running or len(self.pending_jobs) > 0

    def take(self):
        if len(self.pending_jobs) == 0:
            return None
        job_args = self.pending_jobs[0]
        del self.pending_jobs[0]
        return job_args

    def add(self, job_args):
        if len(self.pending_jobs) > self.max_size:
            raise Exception(f"Reached limit of pending runs: {self.max_size} - wait until current run has completed.")
        self.pending_jobs.append(job_args)
        if config.debug:
            print(f"JobQueue {self.name} - Added pending job: {job_args}")

    def cancel(self):
        self.pending_jobs = []
        self.job_running = False

    def pending_text(self):
        if len(self.pending_jobs) == 0:
            return ""
        if self.name == JobQueue.JOB_QUEUE_SD_RUNS_KEY:
            return _(" (Pending runs: {0})").format(len(self.pending_jobs))
        elif self.name == JobQueue.JOB_QUEUE_PRESETS_KEY:
            return _("Pending schedules: {0}").format(len(self.pending_jobs))

    def estimate_time(self, gen_config=None) -> int:
        """
        Estimate the total time in seconds for all pending jobs in this queue.
        This method must be overridden by specific queue implementations.
        
        Args:
            gen_config: Optional GenConfig instance for calculating total jobs
            
        Returns:
            Estimated time in seconds
            
        Raises:
            NotImplementedError: If the method is not overridden by a subclass
        """
        raise NotImplementedError("estimate_time() must be implemented by specific queue implementations")


class SDRunsQueue(JobQueue):
    """Queue for managing Stable Diffusion runs."""
    
    def __init__(self, max_size=50):
        super().__init__(JobQueue.JOB_QUEUE_SD_RUNS_KEY, max_size)
    
    def estimate_time(self, gen_config=None) -> int:
        """
        Estimate the total time in seconds for all pending SD runs.
        
        Args:
            gen_config: Optional GenConfig instance for calculating total jobs
            
        Returns:
            Estimated time in seconds
        """
        total_time = 0
        logger.debug(f"SDRunsQueue.estimate_time - pending jobs: {len(self.pending_jobs)}")
        for run_config in self.pending_jobs:
            job_time = run_config.estimate_time(gen_config)
            total_time += job_time
            logger.debug(f"SDRunsQueue.estimate_time - job time: {job_time}s, total so far: {total_time}s")
        return total_time


class PresetSchedulesQueue(JobQueue):
    """Queue for managing preset schedules."""
    
    def __init__(self, max_size=50, get_run_config_callback=None, get_current_schedule_callback=None):
        super().__init__(JobQueue.JOB_QUEUE_PRESETS_KEY, max_size)
        self.get_run_config_callback = get_run_config_callback
        self.get_current_schedule_callback = get_current_schedule_callback
    
    def estimate_time(self, gen_config=None) -> int:
        """
        Estimate the total time in seconds for all pending preset schedules.
        
        Args:
            gen_config: Optional GenConfig instance for calculating total jobs
            
        Returns:
            Estimated time in seconds
        """
        if not self.get_run_config_callback or not self.get_current_schedule_callback:
            return 0
            
        total_time = 0
        run_config = self.get_run_config_callback()
        logger.debug(f"PresetSchedulesQueue.estimate_time - pending schedules: {len(self.pending_jobs)}")
        
        for schedule_args in self.pending_jobs:
            try:
                schedule = self.get_current_schedule_callback()
                if schedule is None:
                    continue
                    
                # Get total generations for this schedule
                total_generations = schedule.total_generations(run_config.total)
                logger.debug(f"PresetSchedulesQueue.estimate_time - schedule total_generations: {total_generations}")
                
                # Calculate total jobs by dividing maximum_gens by n_latents
                total_jobs = gen_config.maximum_gens_per_latent() if gen_config else 1
                logger.debug(f"PresetSchedulesQueue.estimate_time - total_jobs: {total_jobs}, n_latents: {run_config.n_latents}")
                
                # Get time estimate for all jobs
                schedule_time = TimeEstimator.estimate_queue_time(total_jobs * total_generations, run_config.n_latents)
                total_time += schedule_time
                print(f"PresetSchedulesQueue.estimate_time - schedule time: {schedule_time}s, total so far: {total_time}s")
                
            except Exception as e:
                print(f"Error estimating time for schedule: {schedule_args}")
                print(f"Error details: {str(e)}")
                continue
                
        return total_time