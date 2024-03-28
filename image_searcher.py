import glob
import re

from config import config
from workflow_prompt import WorkflowPrompt


class ImageSearcher:
    IMAGES_DIR = config.image_searcher_dir
    IMAGES_DIR_2 = config.image_searcher_dir2

    def __init__(self):
        pass

    def get_methods(self, obj):
        return [method for method in dir(obj) if callable(getattr(obj, method))]

    def get_method(self, prompt, get_attr):
        methods = self.get_methods(prompt)
        method_name = get_attr if get_attr.startswith("get_") else "get_" + get_attr
        for method in methods:
            if method == method_name:
                return getattr(prompt, method)
        raise Exception("Failed to find method name " + method_name)

    def get_images_by_attr_pattern(self, _dir=IMAGES_DIR, attr="model", pattern=".*"):
        dir_pattern = _dir + "\\**/CUI*"
        cui_images = glob.glob(dir_pattern, recursive=True)
        matching_images = []
        for image in cui_images:
            try:
                prompt = WorkflowPrompt(image)
                method = self.get_method(prompt, attr)
                value = method()
                if value:
                    if re.search(pattern.lower(), value.lower()):
                        matching_images.append(image)
                    else:
                        print("Non-matching: " + str(value))
            except Exception as e:
                print(e)
        return matching_images

    def get_images(self, dirs=[], attr="model", pattern=".*"):
        images = []
        for _dir in dirs:
            dir_images = self.get_images_by_attr_pattern(_dir, attr, pattern=pattern)
            images.extend(dir_images)
        return images

    def get_images_by_model(self, pattern=".*", dirs=[IMAGES_DIR]):
        return self.get_images(dirs=dirs, pattern=pattern)

    def get_images_by_xl_model(self, model_tag="", dirs=[IMAGES_DIR]):
        return self.get_images_by_model(pattern="XL\\\\"+model_tag, dirs=dirs)

if __name__ == "__main__":
    searcher = ImageSearcher()

    # TRC VAEs
    # print("[")
    # for path in searcher.get_images(attr="vae", pattern="^TRC")
    #     print("\"" + path.replace("\\", "\\\\") + "\"")
    # print("]")

    # realvisXLV20 images
    for path in searcher.get_images_by_xl_model("realvisXLV20"):
        print("\"" + path.replace("\\", "\\\\") + "\"")

