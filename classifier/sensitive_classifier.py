import re
import joblib
from bs4 import BeautifulSoup


class SensitiveClassifier:

    def __init__(self):
        self.vectorizer = joblib.load("classifier/vectorizer_balanced_20k_features.pkl")

        self.classifier = joblib.load("classifier/classifier_balanced_20k_features.pkl")

        self.labels = self.classifier.classes_

    def preprocess(self, text: str) -> str:
        text = text.lower()

        text = re.sub(r"[^a-zA-Z0-9 ]", " ", text)

        return text

    def classify_html(self, html: str):

        soup = BeautifulSoup(html, "html.parser")

        text = soup.get_text(separator=" ")

        text = self.preprocess(text)

        X = self.vectorizer.transform([text])

        prediction = self.classifier.predict(X)[0]

        probabilities = self.classifier.predict_proba(X)[0]

        scores = {label: float(prob) for label, prob in zip(self.labels, probabilities)}

        return {
            "predicted_category": prediction,
            "is_sensitive": prediction != "Non-sensitive",
            "scores": scores,
        }
