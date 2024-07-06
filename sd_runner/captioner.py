
from blip.blip import WAS_BLIP_Model_Loader, WAS_BLIP_Analyze_Image


class Captioner:
    def __init__(self):
        self.mode = "caption"
        self.blip_model = WAS_BLIP_Model_Loader().blip_model(self.mode)[0]
        self.analyze_image = WAS_BLIP_Analyze_Image()
    
    def caption(self, image_path):
        answer = self.analyze_image.blip_caption_image(image_path, self.mode, "Please provide a detailed caption for this image.", blip_model=self.blip_model)
        return answer[0]

