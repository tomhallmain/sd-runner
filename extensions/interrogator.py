from collections import defaultdict
from enum import Enum
import glob
import pyjson5
import os
import time

from blip.blip import WAS_BLIP_Model_Loader, WAS_BLIP_Analyze_Image

from utils.config import config
from utils.utils import Utils


class AnswerType(Enum):
    YES_NO = 1
    YES_NO_REVERSED = 2
    NUMERIC = 3
    TEXT = 4


class State(Enum):
    UNSEEN = 0
    REVIEW_BASED_ON_INITIAL_QUESTIONS = 1
    SEEN_AFTER_INITIAL_QUESTIONS = 2
    REVIEW_BASED_ON_MAIN_QUESTIONS = 3
    SEEN_AFTER_MAIN_QUESTIONS = 4

    def __str__(self) -> str:
        return self.name


class ImageData:
    def __init__(self, path):
        self.path = path
        self.categories = {}
        self.state = State.UNSEEN

    def set_attr_by_y_n_answer(self, category, answer, reversed=False):
        answer = answer.lower()
        value = (answer.startswith("y") and len(answer) == 1) or answer == "yes" or answer.startswith("yes") or answer == "both" or answer.startswith("both")
        self.categories[category] = value if not reversed else not value

    def set_category_by_text_answer(self, category, answer):
        self.categories[category] = answer

    @staticmethod
    def get_lambda_for_category(category, answer_type=AnswerType.YES_NO):
        if AnswerType.YES_NO == answer_type:
            return lambda image_data, answer: image_data.set_attr_by_y_n_answer(category, answer)
        if AnswerType.YES_NO_REVERSED == answer_type:
            return lambda image_data, answer: image_data.set_attr_by_y_n_answer(category, answer, reversed=True)
        if AnswerType.NUMERIC == answer_type:
            return lambda image_data, answer: image_data.set_attr_by_numeric_answer(category, answer)
        if AnswerType.TEXT == answer_type:
            return lambda image_data, answer: image_data.set_attr_by_text_answer(category, answer)
        raise Exception("Unhandled answer type: " + str(answer_type))




class Interrogator:
    IMG_TEMPS_DIR = config.img_temps_dir
    DEFAULT_ANSWER_TYPE = AnswerType.YES_NO
    allowed_extensions = Utils.IMAGE_EXTENSIONS

    def __init__(self, directory="."):
        self.directory = directory
        self.mode = "interrogate"
        self.blip_model = WAS_BLIP_Model_Loader().blip_model(self.mode)[0]
        self.analyze_image = WAS_BLIP_Analyze_Image()
        self.questions = {}
        self.image_data = defaultdict(list)
        self.overridden_answer_types = {}

    def gather_images(self, state=State.UNSEEN):
        for ext in Interrogator.allowed_extensions:
            for file_path in sorted(glob.glob(os.path.join(self.directory, "*" + ext))):
                self.image_data[state].append(ImageData(file_path))

    def override_answer_types(self, answer_type, categories):
        for category in categories:
            self.overridden_answer_types[category] = answer_type

    def interrogate(self, image_data):
        for category, question in self.questions.items():
            answer = self.analyze_image.blip_caption_image(image_data.path, self.mode, question, blip_model=self.blip_model)
            print(f"Question: \"{question}\" - Answer \"{answer[0]}\"")
            answer_type = self.overridden_answer_types[category] if category in self.overridden_answer_types else Interrogator.DEFAULT_ANSWER_TYPE
            routing_func = ImageData.get_lambda_for_category(category, answer_type=answer_type)
            routing_func(image_data, answer[0])

    def update_state(self, old_state=State.REVIEW_BASED_ON_INITIAL_QUESTIONS, new_state=State.SEEN_AFTER_INITIAL_QUESTIONS):
        old_state_list = self.image_data[old_state]
        for image_data in old_state_list:
            image_data.state = new_state
        self.image_data[new_state].extend(old_state_list)
        old_state_list.clear()

    def state_has_images_remaining(self, state=State.UNSEEN):
        if state not in self.image_data:
            raise Exception(f"State {state} not found in image data.")
        return len(self.image_data[state]) > 0

    def interrogate_batch(self, max=100, state=State.UNSEEN, new_state=State.REVIEW_BASED_ON_INITIAL_QUESTIONS):
        count = 0
        to_remove = []
        state_image_data = self.image_data[state]
        new_state_image_data = self.image_data[new_state]
        for i in range(len(state_image_data)):
            image_data = state_image_data[i]
            try:
                self.interrogate(image_data)
            except Exception as e:
                print(e)
            image_data.state = new_state
            to_remove.append(image_data)
            new_state_image_data.append(image_data)
            count += 1
            if count >= max:
                break
        for image_data in to_remove:
            state_image_data.remove(image_data)

    def interrogate_all(self):
        for image_data in self.image_data:
            self.interrogate(image_data)

    def add_question(self, question, routing_func):
        self.questions[question] = routing_func

    def report(self, full=False):
        for state, image_data_list in self.image_data.items():
            print(f"State: {state} - Count: {len(image_data_list)}")
            if full:
                for image_data in image_data_list:
                    print(image_data.path)
                    print(image_data.categories)

    def get_images_yes_for_categories(self, categories=[], state=State.REVIEW_BASED_ON_INITIAL_QUESTIONS):
        _dict = {}
        for category in categories:
            _dict[category] = True
        return self.get_images_for_category_values(categories=_dict, state=state)

    def get_images_for_category_values(self, categories={}, state=State.REVIEW_BASED_ON_INITIAL_QUESTIONS):
        matching_images = []
        state_image_data = self.image_data[state]
        for image_data in state_image_data:
            all_categories_match = True
            for category, value in categories.items():
                if category not in image_data.categories or image_data.categories[category] != value:
                    all_categories_match = False
                    break
            if all_categories_match:
                matching_images.append(image_data.path)
        return matching_images

    def get_images_for_category_values_any_true(self, categories=[], state=State.REVIEW_BASED_ON_INITIAL_QUESTIONS):
        matching_images = []
        state_image_data = self.image_data[state]
        for image_data in state_image_data:
            for category in categories:
                if category in image_data.categories and image_data.categories[category]:
                    print(image_data.path)
                    print(image_data.categories)
                    matching_images.append(image_data.path)
                    break
        return matching_images

    def move_images(self, images, relative_dir, state=State.REVIEW_BASED_ON_INITIAL_QUESTIONS, remove_from_image_data=False):
        for image in images:
            base_dir = os.path.join(Interrogator.IMG_TEMPS_DIR, relative_dir)
            basename = os.path.basename(image)
            new_filename = os.path.join(base_dir, basename)
            os.rename(image, new_filename)
            print(f"Moved image file {basename} to {relative_dir}")
        if remove_from_image_data:
            state_image_data = self.image_data[state]
            for i in range(len(state_image_data) - 1, -1, -1):
                image_data = state_image_data[i]
                if image_data.path in images:
                    del state_image_data[i]


def main():
    interrogator = Interrogator(config.interrogator_interrogation_dir)
    interrogator.gather_images()
    interrogator.report()

    # Initial questions
    # iniitial_questions = pyjson5.load(open(config.interrogator_initial_questions_file, "r"))
    # interrogator.questions = initial_questions["questions"]
    # initial_question_categories = initial_questions["categories"]

    # while interrogator.state_has_images_remaining(State.UNSEEN):
    #     interrogator.interrogate_batch(max=40, state=State.UNSEEN, new_state=State.REVIEW_BASED_ON_INITIAL_QUESTIONS)
    #     excluded = interrogator.get_images_for_category_values(categories=initial_question_categories, state=State.REVIEW_BASED_ON_INITIAL_QUESTIONS)
    #     interrogator.move_images(excluded, "_to_review", state=State.REVIEW_BASED_ON_INITIAL_QUESTIONS, remove_from_image_data=True)
    #     interrogator.update_state(old_state=State.REVIEW_BASED_ON_INITIAL_QUESTIONS, new_state=State.SEEN_AFTER_INITIAL_QUESTIONS)
    #     interrogator.report()
    #     time.sleep(10)

    # TODO REMOVE
    interrogator.update_state(old_state=State.UNSEEN, new_state=State.SEEN_AFTER_INITIAL_QUESTIONS)

    # Main questions

    interrogator.questions = pyjson5.load(open(config.interrogator_questions_file, "r"))
    folder_category_mappings = pyjson5.load(open(config.interrogator_folder_category_mappings_file, "r"))
    while interrogator.state_has_images_remaining(State.SEEN_AFTER_INITIAL_QUESTIONS):
        interrogator.interrogate_batch(max=10, state=State.SEEN_AFTER_INITIAL_QUESTIONS, new_state=State.REVIEW_BASED_ON_MAIN_QUESTIONS)
        for folder, categories in folder_category_mappings.items():
            interrogator.move_images(interrogator.get_images_yes_for_categories(categories, state=State.REVIEW_BASED_ON_MAIN_QUESTIONS), folder, state=State.REVIEW_BASED_ON_MAIN_QUESTIONS)
        interrogator.update_state(old_state=State.REVIEW_BASED_ON_MAIN_QUESTIONS, new_state=State.SEEN_AFTER_MAIN_QUESTIONS)
        interrogator.report()
        time.sleep(10)


if __name__ == "__main__":
    main()
