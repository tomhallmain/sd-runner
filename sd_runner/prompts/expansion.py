


class Expansion:
    expansions = []

    def __init__(self, id, text) -> None:
        self.id = id
        self.text = text

    def is_valid(self):
        return self.id is not None and self.id != "" and self.text is not None and self.text != ""

    def to_dict(self):
        return {
            'id': self.id,
            'text': self.text
            }

    @staticmethod
    def from_dict(_dict):
        return Expansion(id=_dict['id'], text=_dict['text'])


    @staticmethod
    def contains_expansion(id):
        for expansion in Expansion.expansions:
            if id == expansion.id:
                return True
        return False

    @staticmethod
    def get_expansion_text_by_id(id):
        for expansion in Expansion.expansions:
            if id == expansion.id:
                return expansion.text
        raise Exception(f"No expansion found with id: {id}. Set it on the Expansions Window.")

