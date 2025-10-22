"""
Optional image format converter module.

This module provides functionality to convert various image formats to standard formats
that can be used by the generator software. It's designed to be optional - if required
dependencies are missing, it will gracefully fail rather than breaking the core functionality.

Supported formats:
- RAW formats: .raw, .cr2, .nef, .arw, .dng
- Image formats: .bmp, .svg, .avif
- Video formats: .mp4, .avi, .mov, .mkv, .webm, .gif (extracts random frame)
- Document formats: .pdf (first page), .html/.htm (rendered snapshot)
"""

import os
import tempfile
import asyncio
import random
from typing import Optional, Union, Dict, Set
from pathlib import Path

from utils.logging_setup import get_logger

logger = get_logger("image_converter")

class ConversionFailedError(RuntimeError):
    """Custom exception for image conversion failures that should not show tracebacks."""
    pass

class ImageConverter:
    """Handles conversion of various image formats to standard formats."""
    
    # Supported input formats that need conversion
    CONVERTIBLE_FORMATS = {
        # RAW formats
        '.raw', '.cr2', '.nef', '.arw', '.dng',
        # Image formats
        '.bmp', '.svg', '.avif',
        # Video formats
        '.mp4', '.avi', '.mov', '.mkv', '.webm', '.gif',
        # Document formats
        '.pdf', '.html', '.htm',
    }
    
    # Standard output format
    OUTPUT_FORMAT = '.png'
    
    def __init__(self):
        """Initialize the image converter with optional dependencies."""
        self._converter_available = False
        self._conversion_methods = set()
        self._temporary_directory = None
        self._converted_files = {}  # Maps original path to converted path
        
        # Try to initialize conversion capabilities
        self._initialize_converter()
        self._setup_temporary_directory()
    
    def _setup_temporary_directory(self):
        """Set up temporary directory for converted files."""
        try:
            self._temporary_directory = tempfile.TemporaryDirectory(prefix="sd_runner_converted_")
            logger.debug(f"Created temporary directory: {self._temporary_directory.name}")
        except Exception as e:
            logger.error(f"Failed to create temporary directory: {e}")
            self._temporary_directory = None
    
    def _initialize_converter(self) -> None:
        """Initialize the image converter with available libraries."""
        # Check for PIL/Pillow (for basic image conversion)
        try:
            import PIL
            from PIL import Image
            self._conversion_methods.add('pil')
            logger.debug("PIL/Pillow available for image conversion")
        except ImportError:
            logger.debug("PIL/Pillow not available for image conversion")
        
        # Check for OpenCV (for video frame extraction)
        try:
            import cv2
            self._conversion_methods.add('opencv')
            logger.debug("OpenCV available for video conversion")
        except ImportError:
            logger.debug("OpenCV not available for video conversion")
        
        # Check for rawpy (for RAW files)
        try:
            import rawpy
            self._conversion_methods.add('rawpy')
            logger.debug("rawpy available for RAW conversion")
        except ImportError:
            logger.debug("rawpy not available for RAW conversion")
        
        # Check for pypdfium2 (for PDF conversion)
        try:
            import pypdfium2
            self._conversion_methods.add('pypdfium2')
            logger.debug("pypdfium2 available for PDF conversion")
        except ImportError:
            logger.debug("pypdfium2 not available for PDF conversion")
        
        # Check for cairosvg (for SVG conversion)
        try:
            import cairosvg
            self._conversion_methods.add('cairosvg')
            logger.debug("cairosvg available for SVG conversion")
        except ImportError:
            logger.debug("cairosvg not available for SVG conversion")
        
        # Check for pyppeteer (for HTML conversion)
        try:
            from pyppeteer import launch
            self._conversion_methods.add('pyppeteer')
            logger.debug("pyppeteer available for HTML conversion")
        except ImportError:
            logger.debug("pyppeteer not available for HTML conversion")
        
        # Set availability based on having at least one conversion method
        self._converter_available = len(self._conversion_methods) > 0
        
        if not self._converter_available:
            logger.warning("No image conversion libraries available. Image format conversion will be disabled.")
        else:
            logger.info(f"Image converter initialized with methods: {', '.join(self._conversion_methods)}")
    
    def needs_conversion(self, file_path: Union[str, Path]) -> bool:
        """
        Check if a file needs format conversion.
        
        Args:
            file_path: Path to the image file
            
        Returns:
            bool: True if the file needs conversion, False otherwise
        """
        if not file_path:
            return False
        
        file_path = Path(file_path)
        if not file_path.exists():
            return False
        
        # Check file extension
        extension = file_path.suffix.lower()
        return extension in self.CONVERTIBLE_FORMATS
    
    def convert_image(self, input_path: Union[str, Path], output_path: Optional[Union[str, Path]] = None) -> Optional[str]:
        """
        Convert an image to a standard format.
        
        Args:
            input_path: Path to the input image
            output_path: Optional output path. If None, creates a temporary file
            
        Returns:
            str: Path to the converted image, or None if conversion failed
        """
        if not self._converter_available:
            raise ConversionFailedError("Image conversion not available - required libraries are missing")
        
        input_path = Path(input_path)
        if not input_path.exists():
            raise FileNotFoundError(f"Input file does not exist: {input_path}")
        
        if not self.needs_conversion(input_path):
            logger.debug(f"File {input_path} does not need conversion")
            return str(input_path)
        
        # Check if already converted
        if str(input_path) in self._converted_files:
            logger.debug(f"Using cached conversion for {input_path}")
            return self._converted_files[str(input_path)]
        
        # Determine output path
        if output_path is None:
            if self._temporary_directory is None:
                raise RuntimeError("Temporary directory not available")
            temp_name = f"converted_{input_path.stem}_{hash(str(input_path))}{self.OUTPUT_FORMAT}"
            output_path = Path(self._temporary_directory.name) / temp_name
        else:
            output_path = Path(output_path)
        
        try:
            extension = input_path.suffix.lower()
            
            if extension in ['.raw', '.cr2', '.nef', '.arw', '.dng']:
                if 'rawpy' in self._conversion_methods:
                    result = self._convert_raw(input_path, output_path)
                else:
                    raise ConversionFailedError("RAW conversion requires rawpy library")
            elif extension in ['.mp4', '.avi', '.mov', '.mkv', '.webm', '.gif']:
                if 'opencv' in self._conversion_methods:
                    result = self._convert_video(input_path, output_path)
                else:
                    raise ConversionFailedError("Video conversion requires OpenCV library")
            elif extension == '.pdf':
                if 'pypdfium2' in self._conversion_methods:
                    result = self._convert_pdf(input_path, output_path)
                else:
                    raise ConversionFailedError("PDF conversion requires pypdfium2 library")
            elif extension == '.svg':
                if 'cairosvg' in self._conversion_methods:
                    result = self._convert_svg(input_path, output_path)
                else:
                    raise ConversionFailedError("SVG conversion requires cairosvg library")
            elif extension in ['.html', '.htm']:
                if 'pyppeteer' in self._conversion_methods:
                    result = self._convert_html(input_path, output_path)
                else:
                    raise ConversionFailedError("HTML conversion requires pyppeteer library")
            elif extension in ['.bmp', '.avif']:
                if 'pil' in self._conversion_methods:
                    result = self._convert_with_pil(input_path, output_path)
                else:
                    raise ConversionFailedError(f"{extension.upper()} conversion requires PIL library")
            else:
                raise ConversionFailedError(f"Unsupported format: {extension}")
            
            # Cache the conversion
            self._converted_files[str(input_path)] = result
            return result
                
        except Exception as e:
            logger.error(f"Failed to convert image {input_path}: {e}")
            return None
    
    def _convert_with_pil(self, input_path: Path, output_path: Path) -> str:
        """Convert image using PIL/Pillow."""
        from PIL import Image
        
        with Image.open(input_path) as img:
            # Convert to RGB if necessary (handles RGBA, P, etc.)
            if img.mode in ('RGBA', 'P'):
                img = img.convert('RGB')
            
            img.save(output_path, 'PNG')
        
        logger.debug(f"Converted {input_path} to {output_path} using PIL")
        return str(output_path)
    
    def _convert_raw(self, input_path: Path, output_path: Path) -> str:
        """Convert RAW image using rawpy."""
        import rawpy
        from PIL import Image
        
        logger.info(f"Converting RAW image: {input_path}")
        with rawpy.imread(str(input_path)) as raw:
            # Process RAW image
            rgb = raw.postprocess()
            
            # Convert to PIL Image and save
            img = Image.fromarray(rgb)
            img.save(output_path, 'PNG')
        
        logger.debug(f"Converted RAW {input_path} to {output_path} using rawpy")
        return str(output_path)
    
    def _convert_video(self, input_path: Path, output_path: Path) -> str:
        """Extract a random frame from video using OpenCV."""
        import cv2
        
        logger.info(f"Extracting frame from video: {input_path}")
        cap = cv2.VideoCapture(str(input_path))
        try:
            # Get total frame count
            total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            if total_frames <= 0:
                raise ValueError("Could not determine video frame count")
            
            # Select a random frame
            frame_number = random.randint(0, total_frames - 1)
            cap.set(cv2.CAP_PROP_POS_FRAMES, frame_number)
            
            ret, frame = cap.read()
            if not ret:
                raise ValueError("Could not read the selected frame")
            
            # Save as PNG
            cv2.imwrite(str(output_path), frame)
            logger.debug(f"Extracted frame {frame_number} from {input_path} to {output_path}")
            return str(output_path)
        finally:
            cap.release()
    
    def _convert_pdf(self, input_path: Path, output_path: Path) -> str:
        """Extract the first page from a PDF as an image."""
        import pypdfium2
        
        logger.info(f"Extracting first page from PDF: {input_path}")
        pdf = pypdfium2.PdfDocument(str(input_path))
        if len(pdf) > 0:
            page = pdf[0]
            # Use a higher scale for better quality
            image = page.render(scale=4).to_pil()
            image.save(output_path, 'PNG')
            logger.debug(f"Extracted first page from {input_path} to {output_path}")
            return str(output_path)
        else:
            raise ValueError("PDF has no pages")
    
    def _convert_svg(self, input_path: Path, output_path: Path) -> str:
        """Convert an SVG file to a PNG image."""
        import cairosvg
        
        logger.info(f"Converting SVG to PNG: {input_path}")
        cairosvg.svg2png(url=str(input_path), write_to=str(output_path))
        logger.debug(f"Converted SVG {input_path} to {output_path}")
        return str(output_path)
    
    def _convert_html(self, input_path: Path, output_path: Path) -> str:
        """Convert an HTML file to a PNG image via PDF."""
        from pyppeteer import launch
        
        logger.info(f"Converting HTML to image: {input_path}")
        
        # First convert HTML to PDF
        pdf_path = Path(self._temporary_directory.name) / f"{input_path.stem}_temp.pdf"
        
        # Convert HTML to PDF using Pyppeteer
        async def convert_html_to_pdf():
            browser = await launch(headless=True)
            page = await browser.newPage()
            
            # Read the HTML file
            with open(input_path, 'r', encoding='utf-8') as f:
                html_content = f.read()
            
            # Set the content and wait for network idle
            await page.setContent(html_content, {'waitUntil': 'networkidle0'})
            
            # Generate PDF with good quality settings
            await page.pdf({
                'path': str(pdf_path),
                'format': 'A4',
                'printBackground': True,
                'margin': {
                    'top': '0',
                    'right': '0',
                    'bottom': '0',
                    'left': '0'
                }
            })
            
            await browser.close()
        
        # Run the async function
        asyncio.get_event_loop().run_until_complete(convert_html_to_pdf())
        
        # Now extract the first page as an image using our existing PDF extraction
        result = self._convert_pdf(pdf_path, output_path)
        
        # Clean up temporary PDF
        try:
            pdf_path.unlink()
        except Exception:
            pass
        
        logger.debug(f"Converted HTML {input_path} to {output_path}")
        return result
    
    def is_available(self) -> bool:
        """Check if image conversion is available."""
        return self._converter_available
    
    def get_supported_formats(self) -> set:
        """Get the set of supported input formats."""
        return self.CONVERTIBLE_FORMATS.copy()
    
    def get_available_methods(self) -> set:
        """Get the set of available conversion methods."""
        return self._conversion_methods.copy()
    
    def cleanup(self) -> None:
        """Clean up temporary files and directory."""
        logger.info("Cleaning up image converter temporary files")
        
        # Clear the cache
        self._converted_files.clear()
        
        # Clean up temporary directory
        if self._temporary_directory is not None:
            try:
                self._temporary_directory.cleanup()
                logger.debug("Cleaned up temporary directory")
            except Exception as e:
                logger.warning(f"Failed to clean up temporary directory: {e}")
            finally:
                self._temporary_directory = None
        
        # Recreate temporary directory for future use
        self._setup_temporary_directory()
    
    def clear_cache(self) -> None:
        """Clear the conversion cache without cleaning up files."""
        self._converted_files.clear()
        logger.debug("Cleared image converter cache")


# Global converter instance
_converter = None

def get_converter() -> ImageConverter:
    """Get the global image converter instance."""
    global _converter
    if _converter is None:
        _converter = ImageConverter()
    return _converter

def convert_image_if_needed(file_path: Union[str, Path]) -> Optional[str]:
    """
    Convert an image file if it needs conversion.
    
    Args:
        file_path: Path to the image file
        
    Returns:
        str: Path to the converted image, or original path if no conversion needed
        
    Raises:
        ConversionFailedError: If conversion is required but fails or libraries are missing
    """
    converter = get_converter()
    
    if not converter.needs_conversion(file_path):
        return str(file_path)
    
    if not converter.is_available():
        raise ConversionFailedError(f"Image conversion not available - required libraries are missing for {file_path}")
    
    try:
        converted_path = converter.convert_image(file_path)
        if converted_path:
            logger.info(f"Converted image: {file_path} -> {converted_path}")
            return converted_path
        else:
            raise ConversionFailedError(f"Image conversion failed for {file_path}")
    except Exception as e:
        # Just re-raise the original exception without wrapping it
        raise

def cleanup_converter() -> None:
    """Clean up the global image converter."""
    global _converter
    if _converter is not None:
        _converter.cleanup()

def clear_converter_cache() -> None:
    """Clear the global image converter cache."""
    global _converter
    if _converter is not None:
        _converter.clear_cache()
