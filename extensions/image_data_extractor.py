from PIL import Image
import glob
import json
import os
import sys

import pprint

from utils.config import config

has_imported_sd_prompt_reader = False
try:
    sys.path.insert(0, config.sd_prompt_reader_loc)
    from sd_prompt_reader.image_data_reader import ImageDataReader
    has_imported_sd_prompt_reader = True
except Exception as e:
    print(e)
    print("Failed to import SD Prompt Reader!")


class ImageDataExtractor:
    EXTENSIONS = [".png", ".jpg", ".jpeg", ".tiff", ".webp"]
    CLASS_TYPE = "class_type"
    INPUTS = "inputs"
    POSITIVE = "positive"
    NEGATIVE = "negative"

    def __init__(self):
        pass

    def is_xl(self, image_path):
        width, height = Image.open(image_path).size
        return width > 768 and height > 768

    def equals_resolution(self, image_path, ex_width=512, ex_height=512):
        width, height = Image.open(image_path).size
        return width == ex_width and height == ex_height

    def higher_than_resolution(self, image_path, max_width=512, max_height=512, inclusive=True):
        width, height = Image.open(image_path).size
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
        width, height = Image.open(image_path).size
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

    def extract_prompt(self, image_path):
        info = Image.open(image_path).info
        if isinstance(info, dict):
            if 'prompt' in info:
                prompt = json.loads(info['prompt'])
                return prompt
            elif 'parameters' in info:
#                print("skipping unhandled Automatic1111 image info")
                return None
            else:
#                print("Unhandled exif data: " + image_path)
                pass
#                print(info)
        else:
            print("Exif data not found: " + image_path)
            return None

    def copy_prompt_to_file(self, image_path, prompt_file_path):
        prompt = self.extract_prompt(image_path)
        with open(prompt_file_path, "w") as store:
            json.dump(prompt, store, indent=2)

    def extract(self, image_path):
        positive = ""
        negative = ""
        prompt_dicts = {}
        node_inputs = {}
        prompt = self.extract_prompt(image_path)

        if prompt is not None:
            for k, v in prompt.items():
                if ImageDataExtractor.CLASS_TYPE in v and ImageDataExtractor.INPUTS in v:
                    #print(v[ImageDataExtractor.CLASS_TYPE])
                    if v[ImageDataExtractor.CLASS_TYPE] == "CLIPTextEncode":
                        prompt_dicts[k] = v[ImageDataExtractor.INPUTS]["text"]
                    elif v[ImageDataExtractor.CLASS_TYPE] == "KSampler":
                        node_inputs[ImageDataExtractor.POSITIVE] = v[ImageDataExtractor.INPUTS][ImageDataExtractor.POSITIVE][0]
                        node_inputs[ImageDataExtractor.NEGATIVE] = v[ImageDataExtractor.INPUTS][ImageDataExtractor.NEGATIVE][0]

            positive = prompt_dicts.get(node_inputs[ImageDataExtractor.POSITIVE], "")
            negative = prompt_dicts.get(node_inputs[ImageDataExtractor.NEGATIVE], "")
            print(f"Positive: \"{positive}\"")
            print(f"Negative: \"{negative}\"")

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
                                print(f"Found control net image - Image ({image_path}) Control Net ({control_net_image_path})")
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
        print("Copied image without exif data to: " + new_image_path)
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
        images = glob.glob(source_dir + "**/*", recursive=True)

        for image_path in images:
            try:
                self.copy_without_exif(image_path, target_dir=target_dir)
                count += 1
            except Exception as e:
                print(e)
            if count > max_count:
                print(f"Reached max image copy count: {max_count}")
                return

        print(f"Copied {count} images without exif.")



def main():
    image_data_extractor = ImageDataExtractor()

if __name__ == "__main__":
    main()
