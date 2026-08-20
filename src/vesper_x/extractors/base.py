from abc import ABC, abstractmethod

class BaseExtractor(ABC):
    @abstractmethod
    def extract_download_links(self, html_content: str) -> list[str]:
        pass
