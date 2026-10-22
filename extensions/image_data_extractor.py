import glob
import json
import os
import sys

from PIL import Image
from PIL.PngImagePlugin import PngInfo

import pprint

from sd_runner.config import config
from lib.logging_setup import get_logger
from lib.pillow_plugins import ensure_pillow_plugins_registered
from lib.utils import Utils

logger = get_logger("image_data_extractor")

# AVIF/HEIF/JXL need plugin registration before Image.open.
ensure_pillow_plugins_registered()

has_imported_sd_prompt_reader = False
try:
    # A missing install leaves this None. Inserting that poisons sys.path and
    # breaks later imports, including pytest's own metadata lookup.
    if config.sd_prompt_reader_loc:
        sys.path.insert(0, config.sd_prompt_reader_loc)
    from sd_prompt_reader.image_data_reader import ImageDataReader
    has_imported_sd_prompt_reader = True
except Exception as e:
    logger.warning(f"Failed to import SD Prompt Reader: {e}")


class ImageDataExtractor:
    EXTENSIONS = Utils.IMAGE_EXTENSIONS
    CLASS_TYPE = "class_type"
    INPUTS = "inputs"
    POSITIVE = "positive"
    NEGATIVE = "negative"
    RELATED_IMAGE_KEY = "related_image"
    ORIGINAL_POSITIVE_TAGS_KEY = "SDR_OriginalPositiveTags"
    ORIGINAL_NEGATIVE_TAGS_KEY = "SDR_OriginalNegativeTags"

    def __init__(self):
        pass

    def is_xl(self, image_path):
        width, height = self.get_image_size(image_path)
        return width > 768 and height > 768

    def get_image_size(self, image_path):
        image = Image.open(image_path)
        width, height = image.size
        image.close()
        return (width, height)

    def equals_resolution(self, image_path, ex_width=512, ex_height=512):
        width, height = self.get_image_size(image_path)
        return width == ex_width and height == ex_height

    def higher_than_resolution(self, image_path, max_width=512, max_height=512, inclusive=True):
        width, height = self.get_image_size(image_path)
        if max_width:
            if inclusive:
                if max_width > width:
                    return False
            elif max_width >= width:
                return False
        if max_height:
            if inclusive:
                if max_height > height:
                    return False
            elif max_height >= height:
                return False
        return True

    def lower_than_resolution(self, image_path, max_width=512, max_height=512, inclusive=True):
        width, height = self.get_image_size(image_path)
        if max_width:
            if inclusive:
                if max_width < width:
                    return False
            elif max_width <= width:
                return False
        if max_height:
            if inclusive:
                if max_height < height:
                    return False
            elif max_height <= height:
                return False
        return True

    def get_related_image_path(self, image_path):
        """Return the source image recorded when this image was generated, or None.

        Written by add_related_image_path for every control-net and IP-adapter
        generation. This is what makes an SDWebUI redo of those workflows
        possible at all: A1111's own metadata records that ControlNet ran and
        with what settings, but never which image it ran on.

        The path is from the generating machine and the file may since have
        moved or been deleted, so callers must check it still exists.
        """
        try:
            image = Image.open(image_path)
        except Exception as e:
            logger.warning(f"Could not open image for metadata: {image_path}: {e}")
            return None
        try:
            info = image.info
            if isinstance(info, dict):
                related = info.get(ImageDataExtractor.RELATED_IMAGE_KEY)
                if related and str(related).strip():
                    return str(related)
            return None
        finally:
            image.close()

    def extract_a1111_parameters(self, image_path):
        """Return the raw SDWebUI ``parameters`` metadata string, or None.

        Kept separate from extract_prompt because the two formats are not
        interchangeable: ComfyUI stores an API-ready workflow dict, SDWebUI a
        human-readable summary that has to be parsed before it means anything.
        """
        try:
            image = Image.open(image_path)
        except Exception as e:
            logger.warning(f"Could not open image for metadata: {image_path}: {e}")
            return None
        try:
            info = image.info
            if isinstance(info, dict) and 'parameters' in info:
                return str(info['parameters'])
            return None
        finally:
            image.close()

    def extract_prompt(self, image_path):
        image = Image.open(image_path)
        info = image.info
        if isinstance(info, dict):
            if 'prompt' in info:
                prompt = json.loads(info['prompt'])
                image.close()
                return prompt
            elif 'parameters' in info:
                # SDWebUI's format. Not a workflow dict, so it cannot be returned
                # here -- see extract_a1111_parameters.
                pass
            else:
#                print("Unhandled exif data: " + image_path)
                pass
#                print(info)
        else:
            logger.warning("Exif data not found: " + image_path)
        image.close()
        return None

    def copy_prompt_to_file(self, image_path, prompt_file_path):
        prompt = self.extract_prompt(image_path)
        with open(prompt_file_path, "w") as store:
            json.dump(prompt, store, indent=2)

    def _node_link_id(self, value):
        """Return the source node id when ``value`` is a link ``[node_id, slot]``."""
        if (
            isinstance(value, (list, tuple))
            and len(value) == 2
            and isinstance(value[0], (str, int))
            and not isinstance(value[0], bool)
            and isinstance(value[1], int)
            and not isinstance(value[1], bool)
        ):
            return str(value[0])
        return None

    def _link_target(self, value):
        """Return ``(node_id, output_slot)`` for a link, or None."""
        node_id = self._node_link_id(value)
        if node_id is None:
            return None
        return node_id, value[1]

    def _resolve_bool_input(self, prompt, value, visited):
        """Resolve a boolean widget or a link to a PrimitiveBoolean (or similar ``value`` node)."""
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value)
        if isinstance(value, str):
            return value.strip().lower() in ("true", "1", "yes", "on")
        node_id = self._node_link_id(value)
        if node_id is None or node_id in visited:
            return False
        inputs = prompt.get(node_id, {}).get(ImageDataExtractor.INPUTS, {})
        if "value" not in inputs:
            return False
        return self._resolve_bool_input(prompt, inputs.get("value"), visited | {node_id})

    def _resolve_text_input(self, prompt, value, visited=None):
        """Resolve a string widget or a link to a string-producing node.

        Follows the nodes this extractor has seen between a CLIP text input and the
        literal prompt: primitive strings, ``StringConcatenate``, ``ComfySwitchNode``
        (the branch selected by ``switch``), and pass-through nodes such as ``PreviewAny``.
        """
        if isinstance(value, str):
            return value
        if isinstance(value, bytes):
            try:
                return value.decode("utf-8", errors="replace")
            except Exception:
                return ""
        node_id = self._node_link_id(value)
        if node_id is None:
            return ""
        if visited is None:
            visited = set()
        if node_id in visited:
            return ""
        path = visited | {node_id}
        node = prompt.get(node_id, {})
        inputs = node.get(ImageDataExtractor.INPUTS, {})
        class_type = node.get(ImageDataExtractor.CLASS_TYPE, "")

        if class_type in ("ComfySwitchNode", "ComfySoftSwitchNode"):
            switch_on = self._resolve_bool_input(prompt, inputs.get("switch"), path)
            selected_key = "on_true" if switch_on else "on_false"
            selected = inputs.get(selected_key, "")
            resolved = self._resolve_text_input(prompt, selected, path)
            # TextGenerate (prompt enhancement) does not save its output in the prompt
            # graph. The official Krea template keeps the typed prompt on the other
            # branch of the same switch, so use that when the selected branch is empty.
            if not str(resolved).strip() and self._text_output_not_stored(prompt, selected, path):
                other_key = "on_false" if switch_on else "on_true"
                other = self._resolve_text_input(prompt, inputs.get(other_key, ""), path)
                if str(other).strip():
                    return other
            return resolved

        if class_type == "StringConcatenate":
            parts = [
                self._resolve_text_input(prompt, inputs.get("string_a", ""), path),
                self._resolve_text_input(prompt, inputs.get("string_b", ""), path),
            ]
            delimiter = inputs.get("delimiter", "")
            if not isinstance(delimiter, str):
                delimiter = self._resolve_text_input(prompt, delimiter, path)
            return delimiter.join(parts)

        # PrimitiveString / PrimitiveStringMultiline store the prompt in ``value``.
        raw_value = inputs.get("value", None)
        if isinstance(raw_value, str) or self._node_link_id(raw_value) is not None:
            return self._resolve_text_input(prompt, raw_value, path)

        # PreviewAny and similar nodes forward their input on ``source``.
        if "source" in inputs:
            return self._resolve_text_input(prompt, inputs.get("source", ""), path)

        return ""

    def _text_output_not_stored(self, prompt, value, visited):
        """True when ``value`` links to a node whose text is produced at runtime.

        ``TextGenerate`` writes ``generated_text`` only into the execution result.
        The saved prompt keeps the node's inputs, not that output. ``PreviewAny``
        in front of such a node does not store the text either.
        """
        node_id = self._node_link_id(value)
        if node_id is None or node_id in visited:
            return False
        node = prompt.get(node_id, {})
        class_type = node.get(ImageDataExtractor.CLASS_TYPE, "")
        if class_type in ("TextGenerate", "TextGenerateLTX2Prompt"):
            return True
        if class_type == "PreviewAny":
            source = node.get(ImageDataExtractor.INPUTS, {}).get("source")
            return self._text_output_not_stored(prompt, source, visited | {node_id})
        return False

    def _resolve_linked_conditioning(self, prompt, link, prompt_dicts, visited):
        """Follow a conditioning link ``[node_id, output_slot]``. Returns None when it is not a link."""
        node_id = self._node_link_id(link)
        if node_id is None:
            return None
        return self._resolve_clip_text(prompt, node_id, prompt_dicts, visited, output_slot=link[1])

    def _resolve_clip_text(self, prompt, node_key, prompt_dicts, visited=None, output_slot=0):
        """Walk conditioning references through intermediate nodes to reach a CLIPTextEncode.

        ``output_slot`` selects which output of a multi-output node to follow.
        ``ReferenceMultiLatent`` output 0 is its positive input and output 1 is its
        negative input (or the positive input again when negative is not connected).
        """
        if visited is None:
            visited = set()
        if node_key is None:
            return ""
        node_key = str(node_key)
        visit_key = (node_key, output_slot)
        if visit_key in visited:
            return ""
        visited.add(visit_key)
        if node_key in prompt_dicts:
            return prompt_dicts[node_key] if output_slot == 0 else ""
        node = prompt.get(node_key, {})
        # ConditioningZeroOut nulls the conditioning. Its input link still points at
        # the positive CLIP encode, but that text is not the negative prompt.
        if node.get(ImageDataExtractor.CLASS_TYPE) == "ConditioningZeroOut":
            return ""
        inputs = node.get(ImageDataExtractor.INPUTS, {})
        conditioning = inputs.get("conditioning")
        if self._node_link_id(conditioning) is not None:
            resolved = self._resolve_linked_conditioning(prompt, conditioning, prompt_dicts, visited)
            return "" if resolved is None else resolved
        # ReferenceMultiLatent (and the same shape): the sampler links to one node
        # twice, and the output slot chooses the positive or negative conditioning.
        positive_link = inputs.get("positive")
        negative_link = inputs.get("negative")
        if self._node_link_id(positive_link) is not None or self._node_link_id(negative_link) is not None:
            if output_slot == 0:
                resolved = self._resolve_linked_conditioning(prompt, positive_link, prompt_dicts, visited)
                return "" if resolved is None else resolved
            if output_slot == 1:
                if self._node_link_id(negative_link) is None:
                    resolved = self._resolve_linked_conditioning(prompt, positive_link, prompt_dicts, visited)
                else:
                    resolved = self._resolve_linked_conditioning(prompt, negative_link, prompt_dicts, visited)
                return "" if resolved is None else resolved
            return ""
        return ""

    def extract(self, image_path):
        positive = ""
        negative = ""
        prompt_dicts = {}
        node_inputs = {}
        has_found_discriminator = False
        prompt = self.extract_prompt(image_path)

        if prompt is not None:
            for k, v in prompt.items():
                if ImageDataExtractor.CLASS_TYPE in v and ImageDataExtractor.INPUTS in v:
                    if v[ImageDataExtractor.CLASS_TYPE] == "CLIPTextEncode":
                        text = v[ImageDataExtractor.INPUTS].get("text", "")
                        # text may be a link [node_id, slot] into a primitive, switch, or concatenate.
                        if self._node_link_id(text) is not None:
                            text = self._resolve_text_input(prompt, text)
                        prompt_dicts[k] = text if isinstance(text, str) else ""
                    elif v[ImageDataExtractor.CLASS_TYPE] == "ImpactWildcardProcessor":
                        positive = v[ImageDataExtractor.INPUTS]["populated_text"]
                    elif (ImageDataExtractor.POSITIVE in v[ImageDataExtractor.INPUTS] and
                          ImageDataExtractor.NEGATIVE in v[ImageDataExtractor.INPUTS]):
                        if has_found_discriminator and v[ImageDataExtractor.CLASS_TYPE].startswith("KSampler"):
                            continue
                        has_found_discriminator = True
                        # Keep the output slot. ReferenceMultiLatent uses one node for both
                        # conditioning streams: output 0 is positive and output 1 is negative.
                        node_inputs[ImageDataExtractor.POSITIVE] = self._link_target(
                            v[ImageDataExtractor.INPUTS][ImageDataExtractor.POSITIVE]
                        )
                        node_inputs[ImageDataExtractor.NEGATIVE] = self._link_target(
                            v[ImageDataExtractor.INPUTS][ImageDataExtractor.NEGATIVE]
                        )

            # Resolve positive/negative through the node graph. ReferenceLatent passes
            # conditioning through. ReferenceMultiLatent exposes positive and negative
            # on output slots 0 and 1 of the same node.
            pos_ref = node_inputs.get(ImageDataExtractor.POSITIVE)
            neg_ref = node_inputs.get(ImageDataExtractor.NEGATIVE)
            if not positive:
                positive = self._resolve_clip_text(prompt, pos_ref[0], prompt_dicts, output_slot=pos_ref[1]) if pos_ref else ""
            negative = self._resolve_clip_text(prompt, neg_ref[0], prompt_dicts, output_slot=neg_ref[1]) if neg_ref else ""

        return (positive, negative)

    def uses_load_images(self, image_path, control_net_image_paths=[]):
        if not control_net_image_paths or len(control_net_image_paths) == 0:
            raise Exception("Control net image not provided.")
        prompt = self.extract_prompt(image_path)

        if prompt is not None:
            for v in prompt.values():
                if ImageDataExtractor.CLASS_TYPE in v:
                    if v[ImageDataExtractor.CLASS_TYPE] == "LoadImage" and ImageDataExtractor.INPUTS in v:
                        loaded_image = v[ImageDataExtractor.INPUTS]["image"]
                        for control_net_image_path in control_net_image_paths:
                            if loaded_image == control_net_image_path:
                                logger.info(f"Found control net image - Image ({image_path}) Control Net ({control_net_image_path})")
                                return control_net_image_path
        return None

    def copy_without_exif(self, image_path, image_copy_path=None, target_dir=None):
        image = Image.open(image_path)
        # strip exif
        data = list(image.getdata())
        image_without_exif = Image.new(image.mode, image.size)
        image_without_exif.putdata(data)

        dirpath = os.path.dirname(image_path) if target_dir is None else target_dir
        basename, extension = os.path.splitext(os.path.basename(image_path))
        if target_dir is None:
            basename += "_"
        new_image_path = os.path.join(dirpath, basename + extension)
        logger.info("Copied image without exif data to: " + new_image_path)
        image_without_exif.save(new_image_path)
        # as a good practice, close the file handler after saving the image.
        image_without_exif.close()

    def print_imageinfo(self, image_path):
        info = Image.open(image_path).info
        print("Image info for image: " + image_path)
        pprint.pprint(info)

    def print_prompt(self, image_path):
        prompt = self.extract_prompt(image_path)
        print("Prompt for image: " + image_path)
        pprint.pprint(prompt)

    def dump_prompt(self, image_path):
        prompt = self.extract_prompt(image_path)
        with open("test1.json", "w") as store:
            json.dump(prompt, store, indent=2)

    def get_image_data_reader(self, image_path):
        if not has_imported_sd_prompt_reader:
            raise Exception("Stable diffusion prompt reader failed to import. Please check log and config.json file.")
        return ImageDataReader(image_path)

    def get_image_prompts(self, image_path):
        image_data = self.get_image_data_reader(image_path)
        if not image_data.tool:
            raise Exception("SD Prompt Reader was unable to parse image file data: " + image_path)
        if image_data.is_sdxl:
            positive = image_data.positive_sdxl
            negative = image_data.negative_sdxl
        else:
            positive = image_data.positive
            negative = image_data.negative
        return positive, negative

    def has_small_face(self):
        """
        A function to determine whether the largest face that exists in the image is smaller than a certain threshold, if it is then return true.
        This could be useful for determining which images need to be inpainted in the face.
        """
        pass # TODO

    def is_coherent(self):
        """
        A function to determine whether or not an image is "coherent" AKA doesn't have extra arms and legs on people etc.
        """
        pass # TODO

    def get_images_by_prompt_load(self, test_images_dir, load_images_dir, includes_any_load_image=False):
        """
        Returns a list of images which have (or have not) used other images in the prompt, for example, as ControlNet or IPAdapter images.
        """
        images = glob.glob(load_images_dir + "\\**/*", recursive=True)
        for filepath in glob.glob(test_images_dir + "\\**/*", recursive=True):
            is_image_file = False
            for ext in ImageDataExtractor.EXTENSIONS:
                if filepath.endswith(ext):
                    is_image_file = True
                    break
            if not is_image_file:
                continue
            image = self.uses_load_images(filepath, images)
            if image:
                if not includes_any_load_image:
                    images.remove(image)
            else:
                if includes_any_load_image:
                    images.remove(image)
        return images


    def copy_dir_images_no_exif(self, source_dir, target_dir=None, max_count=5000):
        count = 0
        all_files = glob.glob(source_dir + "**/*", recursive=True)
        
        # Filter to only image files
        images = []
        for filepath in all_files:
            for ext in ImageDataExtractor.EXTENSIONS:
                if filepath.lower().endswith(ext.lower()):
                    images.append(filepath)
                    break
        
        if target_dir is not None and not os.path.isdir(target_dir):
            os.makedirs(target_dir)

        for image_path in images:
            try:
                self.copy_without_exif(image_path, target_dir=target_dir)
                count += 1
            except Exception as e:
                logger.error(f"Failed to copy {image_path} without exif: {e}")
            if count > max_count:
                logger.info(f"Reached max image copy count: {max_count}")
                return

        logger.info(f"Copied {count} images without exif.")

    def add_related_image_path(self, image_path, related_image_path=""):
        image = Image.open(image_path)
        png_info = PngInfo()
        for k, v in image.info.items():
            png_info.add_text(str(k), str(v))
        png_info.add_text(ImageDataExtractor.RELATED_IMAGE_KEY, str(related_image_path))
        image.save(image_path, pnginfo=png_info)
        image.close()
        if config.debug:
            logger.debug("Added related image path: " + related_image_path)

    def add_prompt_decomposition_to_exif(self, image_path: str, original_positive_tags: str = None, original_negative_tags: str = None):
        """Add original prompt decomposition to EXIF data of the generated image."""
        try:
            image = Image.open(image_path)
            png_info = PngInfo()
            
            # Copy existing EXIF data
            for k, v in image.info.items():
                png_info.add_text(str(k), str(v))
            
            # Add original prompt decomposition
            if original_positive_tags is not None:
                png_info.add_text(ImageDataExtractor.ORIGINAL_POSITIVE_TAGS_KEY, str(original_positive_tags))
            if original_negative_tags is not None:
                png_info.add_text(ImageDataExtractor.ORIGINAL_NEGATIVE_TAGS_KEY, str(original_negative_tags))
            
            # Save with updated EXIF data
            image.save(image_path, pnginfo=png_info)
            image.close()
            
            if config.debug:
                logger.debug(f"Added original prompt decomposition to EXIF: {image_path}")
        except Exception as e:
            logger.error(f"Failed to add prompt decomposition to EXIF for {image_path}: {e}")


def main():
    image_data_extractor = ImageDataExtractor()

if __name__ == "__main__":
    main()
