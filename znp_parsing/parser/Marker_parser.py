import base64
import requests
from PIL import Image, ImageEnhance
from marker.converters.pdf import PdfConverter
from marker.converters.table import TableConverter
from marker.models import create_model_dict
from marker.output import text_from_rendered
from tqdm import tqdm
from openai import OpenAI
from concurrent.futures import ThreadPoolExecutor, as_completed
from marker.config.parser import ConfigParser
import re


class MarkerOnSteroids:
    def __init__(self, model_url="http://localhost:11434/api/generate", ocr_correction_model_name = "Qwen/Qwen3-14B", image_description_model_name="gemma3:12b", context_window_for_image_description=512, page_num=None, ocr_model_url="http://localhost:8555/v1", ocr_correction_chunk_size=128, extract_images=False, extract_tables = True, correct_text_ocr = True, correct_tables_ocr = True):
        config_marker = {}
        if page_num is not None:
            config_marker["page_range"] = page_num
        config_marker['pdftext_workers'] = 2
        config_marker['disable_image_extraction'] = False if extract_images else True
        
        self.model_url = model_url
        self.image_description_model_name = image_description_model_name
        self.ocr_correction_model_name = ocr_correction_model_name
        self.context_window_for_image_description = context_window_for_image_description
        self.ocr_correction_chunk_size = ocr_correction_chunk_size
        self.extract_images = extract_images  
        self.extract_tables = extract_tables
        self.correct_tables_ocr = correct_tables_ocr
        self.correct_text_ocr = correct_text_ocr
        self.ocr_client = OpenAI(base_url=ocr_model_url, api_key="EMPTY") 

        config_parser = ConfigParser(config_marker)
        
        self.text_converter = PdfConverter(
            artifact_dict=create_model_dict(),
            config=config_parser.generate_config_dict()
        )

        self.tables_converter = TableConverter(
            artifact_dict=create_model_dict(),
            config=config_parser.generate_config_dict(),
        )

    
    def parse_page_range(self, page_range_str: str) -> list[int]:
        pages = set()
        for part in page_range_str.split(","):
            if "-" in part:
                start, end = part.split("-")
                pages.update(range(int(start)-1, int(end)))
            else:
                pages.add(int(part)-1)
        return sorted(pages)
    
    def parse_pdf(self, pdf_path: str):
        print("📄 Парсинг PDF...")
        text_rendered = self.text_converter(pdf_path)
        self.text, self.metadata, self.images = text_from_rendered(text_rendered)
        print(f"✅ Найдено {len(self.images)} изображений.")

        print("🔍 Извлечение таблиц...")
        table_rendered = self.tables_converter(pdf_path)
        self.tables, _, _ = text_from_rendered(table_rendered)
        self.tables = self.tables.split('|\n\n|')  
        
        self.tables = [table for table in self.tables if table.strip()]

        print(f"✅ Найдено {len(self.tables)} таблиц.")

    def find_contexts(self):
        print("🔍 Поиск контекста для изображений...")
        words = self.text.split()
        context_dict = {}
        for name in self.images:
            image_index = self.text.find(name)
            if image_index != -1:
                prefix = self.text[:image_index]
                prefix_words = prefix.split()
                context = ' '.join(prefix_words[-self.context_window_for_image_description:])
                context_dict[name] = context
        print(f"✅ Контекст найден для {len(context_dict)} изображений.")
        return context_dict

    def preprocess_image(self, image: Image.Image, output_path="preprocessed_image.jpg") -> str:
        enhancer = ImageEnhance.Contrast(image)
        enhanced_image = enhancer.enhance(2.0)
        enhanced_image.save(output_path)
        with open(output_path, "rb") as img_file:
            return base64.b64encode(img_file.read()).decode("utf-8")

    def describe_image(self, encoded_image: str, context: str) -> str:
        prompt = (
            f"Контекст, где упоминалась картинка: {context}\n"
            "Очень подробно и развернуто опиши все, что ты видишь на этом рисунке/чертеже.\n"
            "Очень важны все технические детали, включая цифры и обозначения.\n"
            "Обращай внимания на текстовый контекст при описании.\n"
            "Ответ дай на русском языке, в ответе не нужны никакие вводные слова, сразу описание."
        )

        payload = {
            "model": self.image_description_model_name,
            "prompt": prompt,
            "stream": False,
            "images": [encoded_image],
        }
        try:
            response = requests.post(self.model_url, json=payload, timeout=5000)
            if response.status_code == 200:
                return response.json().get("response", "Описание не найдено.")
            else:
                return f"Ошибка при запросе: {response.status_code}"
        except:
            return "[Не удалось описать картинку]"
        
    def generate_markdown_with_descriptions(self, descriptions: dict) -> str:
        markdown = self.text
        for name, desc in descriptions.items():
            if name in markdown:
                markdown = markdown.replace(f"![]({name})", f"**Описание изображения:** {desc}")
        return markdown

    def split_text_into_chunks(self, text: str, chunk_size: int) -> list[str]:
        # Поддержка как Markdown заголовков, так и нумерованных (например, "7. Заголовок")
        header_pattern = re.compile(r'^(#{1,6} .+|[0-9]{1,2}\.\s+.+)$', re.MULTILINE)
        chunks = []
        positions = [(m.start(), m.group(0)) for m in header_pattern.finditer(text)]

        if not positions:
            return self._split_large_block(text, chunk_size)

        positions.append((len(text), None))  # Финальный предел

        for i in range(len(positions) - 1):
            start = positions[i][0]
            end = positions[i + 1][0]
            block = text[start:end].strip()
            if len(block) <= chunk_size:
                chunks.append(block)
            else:
                chunks.extend(self._split_large_block(block, chunk_size))

        return chunks


    def _split_large_block(self, block: str, chunk_size: int) -> list[str]:
        sentences = re.split(r'(?<=[.?!])\s+', block)
        chunks = []
        current_chunk = ""

        min_chunk_size = max(1, chunk_size // 4)

        for sentence in sentences:
            if not sentence.strip():
                continue
            if len(current_chunk) + len(sentence) + 1 <= chunk_size:
                current_chunk += "\n" + sentence if current_chunk else sentence
            else:
                if len(current_chunk.strip()) >= min_chunk_size:
                    chunks.append(current_chunk.strip())
                    current_chunk = sentence
                else:
                    # если текущий чанк меньше минимального, продолжаем добавлять к нему
                    current_chunk += "\n" + sentence

        if current_chunk.strip():
            chunks.append(current_chunk.strip())

        return chunks

    def correct_ocr_errors(self, text: str) -> str:
        chunks = self.split_text_into_chunks(text, self.ocr_correction_chunk_size)
        corrected_chunks = [None] * len(chunks)

        def process_chunk(index_chunk):
            index, chunk = index_chunk
            prompt_system = (
                "Ты — помощник, который исправляет OCR-ошибки в тексте. "
                "Сохрани стиль, структуру и слова оригинала точь в точь без изменений, "
                "но исправь орфографические и ocr ошибки. "
                "В качестве ответа верни только исправленный Markdown."
            )

            payload = {
                "model": self.ocr_correction_model_name,
                "messages": [
                    {"role": "system", "content": prompt_system},
                    {"role": "user", "content": chunk}
                ],
                "temperature": 0.3,
                "extra_body": {"chat_template_kwargs": {"enable_thinking": False}},
            }

            try:
                response = self.ocr_client.chat.completions.create(**payload)
                corrected_chunk = response.choices[0].message.content
                corrected_chunk = corrected_chunk.replace('```markdown', '').replace('```', '')
                return index, corrected_chunk
            except Exception as e:
                print(f"❌ Ошибка при обработке чанка {index}: {e}")
                return index, chunk

        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = [executor.submit(process_chunk, (i, chunk)) for i, chunk in enumerate(chunks)]

            for future in tqdm(as_completed(futures), total=len(futures), desc="🔧 Исправление текста параллельно"):
                index, corrected = future.result()
                corrected_chunks[index] = corrected

        return '\n\n'.join(corrected_chunks)


    def correct_table_ocr(self, table: str) -> str:
        prompt_system = (
            "Ответ всегда на языке переданного тебе текста. "
            "Ты — помощник, который исправляет OCR-ошибки в таблицах. "
            "Исправь ошибки распознавания символов в таблице, сохранив формат Markdown. "
            "Не меняй структуру таблицы и не изменяй смысл содержимого. "
            "Исправляй только очевидные OCR-ошибки: пропущенные символы, неправильные буквы, цифры и знаки."
        )

        payload = {
            "model": self.ocr_correction_model_name,
            "messages": [
                {"role": "system", "content": prompt_system},
                {"role": "user", "content": table}
            ],
            "temperature": 0.05,
            "extra_body": {"chat_template_kwargs": {"enable_thinking": False}},
        }

        try:
            response = self.ocr_client.chat.completions.create(**payload)
            corrected = response.choices[0].message.content
            corrected = corrected.replace('```markdown', '').replace('```', '')
            return corrected
        except Exception as e:
            print(f"❌ Ошибка при исправлении таблицы: {e}")
            return table


    def run(self, pdf_path: str):
        self.parse_pdf(pdf_path)

        raw_marker = self.text

        tables_dict = {}    
        if self.extract_tables:
            for i, table in enumerate(self.tables):
                tables_dict[i] = table
                self.text = self.text.replace(table, f'[table_{i}]')
                self.text = self.text.replace(f'|[table_{i}]', f'[table_{i}]')
                self.text = self.text.replace(f'[table_{i}]|', f'[table_{i}]')
        else:
            for i, table in enumerate(self.tables):
                self.text = self.text.replace(table, '')

        if self.correct_text_ocr:
            print("📄 Исправление ошибок OCR")
            self.text = self.correct_ocr_errors(self.text)

        if self.extract_images:
            print("🖼️->📝 Генерация описаний для изображений...")
            context_dict = self.find_contexts()
            img_descriptions = {}
            for name in tqdm(context_dict, desc="🔧 Обработка изображений"):
                context = context_dict[name]
                encoded_image = self.preprocess_image(self.images[name])
                description = self.describe_image(encoded_image, context)
                img_descriptions[name] = description

            print("✅ Все изображения обработаны.")

            self.text = self.generate_markdown_with_descriptions(img_descriptions)
        

        
        if self.extract_tables and self.correct_tables_ocr:
                for i, table in tqdm(tables_dict.items(), desc="🛠️ Исправление таблиц"):
                    table = self.correct_table_ocr(table)
                    tables_dict[i] = table
        if self.correct_tables_ocr or self.correct_text_ocr:
            print("✅ Ошибки OCR исправлены.")

        if self.extract_tables:
            for i, table in tables_dict.items():
                self.text = self.text.replace(f'[table_{i}]', table)

        return raw_marker, self.text
    
import os
from pathlib import Path
import subprocess


def process_pdfs_in_directory(directory):
    output_without_llm_base = Path("without_llm")
    output_with_llm_base = Path("with_llm")

    output_without_llm_base.mkdir(parents=True, exist_ok=True)
    output_with_llm_base.mkdir(parents=True, exist_ok=True)

    directory = Path(directory).resolve()

    for root, dirs, files in os.walk(directory):
        for file in files:
            if file.lower().endswith('.pdf'):
                file_path = Path(root) / file
                relative_path = file_path.relative_to(directory)

                result_file_without_llm = output_without_llm_base / relative_path.with_suffix(".md")
                result_file_with_llm = output_with_llm_base / relative_path.with_suffix(".md")

                # ✅ Создание необходимых поддиректорий
                result_file_without_llm.parent.mkdir(parents=True, exist_ok=True)
                result_file_with_llm.parent.mkdir(parents=True, exist_ok=True)

                if result_file_without_llm.exists() and result_file_with_llm.exists():
                    continue  # Уже обработан

                print(f"🚧 Обработка {relative_path}...")

                pipeline = MarkerOnSteroids(
                    extract_images=False,
                    extract_tables=False,
                    correct_tables_ocr=False,
                    correct_text_ocr=True
                )
                results_without_llm, results_with_llm = pipeline.run(str(file_path))

                with open(result_file_without_llm, 'w', encoding='utf-8') as f:
                    f.write(results_without_llm.replace('```markdown', '').replace('```', ''))

                with open(result_file_with_llm, 'w', encoding='utf-8') as f:
                    f.write(results_with_llm.replace('```markdown', '').replace('```', ''))


process_pdfs_in_directory("NN_docs")