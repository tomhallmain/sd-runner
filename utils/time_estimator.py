from typing import Optional
from utils.globals import Globals
from utils.translations import I18N

_ = I18N._


class TimeEstimator:
    """
    Provides time estimation functionality for image generation jobs.
    
    Current implementation uses DELAY_SECONDS as a baseline for estimation.
    
    Future improvements could include:
    1. Statistical Analysis:
       - Track actual generation times for different workflows
       - Store timing data in a persistent format (JSON/YAML)
       - Build statistical models based on:
         * Workflow type (txt2img, img2img, etc.)
         * Model used
         * Resolution
         * Number of latents
         * System load
         * GPU availability
    
    2. Real-time Monitoring:
       - Track actual job completion times
       - Update estimates based on recent performance
       - Account for system load and resource availability
       - Consider queue position and concurrent jobs
    
    3. Machine Learning:
       - Train models to predict generation times
       - Consider historical patterns
       - Adapt to system performance changes
       - Account for model-specific characteristics
    
    4. User Feedback:
       - Allow users to provide feedback on estimate accuracy
       - Adjust estimates based on user feedback
       - Provide confidence intervals for estimates
    """
    
    @staticmethod
    def estimate_seconds(workflow_type: str,
                        n_latents: int = 1,
                        resolution: Optional[tuple[int, int]] = None) -> int:
        """
        Estimate the time in seconds for a generation job.
        
        Args:
            workflow_type: The type of workflow (e.g., 'txt2img', 'img2img')
            n_latents: Number of latents to generate
            resolution: Optional tuple of (width, height) for resolution
            
        Returns:
            Estimated time in seconds
        """
        # Base time per image in seconds
        base_time = Globals.GENERATION_DELAY_TIME_SECONDS
        
        # Adjust for number of latents
        return int(base_time * n_latents)
    
    @staticmethod
    def format_time(seconds: int) -> str:
        """
        Format a time duration in seconds into a human-readable string.
        
        Args:
            seconds: Time duration in seconds
            
        Returns:
            A formatted string representing the time (e.g. "~2d 3h 30m 15s")
        """
        # Convert to days, hours, minutes and seconds
        days = int(seconds // (24 * 3600))
        seconds = seconds % (24 * 3600)
        hours = int(seconds // 3600)
        seconds = seconds % 3600
        minutes = int(seconds // 60)
        seconds = int(seconds % 60)
        
        # Format the time string
        parts = []
        if days > 0:
            parts.append(_("~{0}d").format(days))
        if hours > 0 or days > 0:
            parts.append(_("{0}h").format(hours))
        if minutes > 0 or hours > 0 or days > 0:
            parts.append(_("{0}m").format(minutes))
        parts.append(_("{0}s").format(seconds))
        
        return " ".join(parts)
    
    @staticmethod
    def estimate_time(workflow_type: str,
                     n_latents: int = 1,
                     resolution: Optional[tuple[int, int]] = None) -> str:
        """
        Estimate the time for a generation job and return as a formatted string.
        
        Args:
            workflow_type: The type of workflow (e.g., 'txt2img', 'img2img')
            n_latents: Number of latents to generate
            resolution: Optional tuple of (width, height) for resolution
            
        Returns:
            A formatted string representing the estimated time
        """
        total_time = TimeEstimator.estimate_seconds(workflow_type, n_latents, resolution)
        return TimeEstimator.format_time(total_time)
    
    @staticmethod
    def estimate_queue_time(queue_size: int,
                          avg_latents_per_job: float = 1.0) -> int:
        """
        Estimate the total time in seconds for all jobs in the queue.
        
        Args:
            queue_size: Number of jobs in the queue
            avg_latents_per_job: Average number of latents per job
            
        Returns:
            Estimated time in seconds
        """
        return int(Globals.GENERATION_DELAY_TIME_SECONDS * queue_size * avg_latents_per_job) 