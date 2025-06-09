import regex as re
import pdfplumber
import json
import os
from ImageProcessor import ImageProcessor
from TextSplitter import  TextSplitter
from TokenCounter import count_tokens

class chunk_codex:

    """
    Чанкер для Кодекс_от_29_12_2004_N_190_ФЗ_Градостроительный_кодекс_Российской.pdf

    """
    def __init__(self, out_dir="chunked_pdf"):
        self.out_dir = out_dir
        self.image_proc = ImageProcessor(out_dir)
        self.subst1 = re.compile(
            r'Градостроительный кодекс Российской Федерации \(с изменениями на \d{1,2} \w+ \d{4} года\) \(редакция, действующая с \d{1,2} \w+ \d{4} года\) Кодекс РФ от \d{2}\.\d{2}\.\d{4} N \d+-\w+ Страница \d+')
        self.subst2 = re.compile(
            r'Внимание! Документ с изменениями и дополнениями \(новая редакция\)\. О последующих изменениях см\. ярлык "Оперативная информация"\s*ИС «Техэксперт: \d+ поколение» Интранет')

        self.first_findall = re.compile(r"\b\d+(?:_\d+)*\.(?!\d)")
        self.first_chunks = re.compile(r"(?=\b\d+(?:_\d+)*\.(?!\d))")
        self.second_split = re.compile(r'(?<=[;)])\s+(?=\d+_?\d*\))')
        self.third_split = re.compile(r"(?<=[;):])\s+(?=[а-яА-ЯёЁ]+(?:_[а-яА-ЯёЁ0-9]+)*\))")
        self.else_split = re.compile(r'(?<=[);:])\s+(?=(?:\d[\d_]*|[a-zA-Zа-яА-Я])\))')
        self.splitter = TextSplitter()


    def is_bold(self, fontname):
        """
        Проверка на жирность
        """
        return 'Bold' in fontname or 'BD' in fontname

    def extract_font(self, line):
        """
        Получаем значение шрифтов всех символов в строке и убираем ненужные значения самих символов

        line: dict, одна линия со страницы документа, которую достали с помощью pdfplumber
        return: dict, очищенная линия со страницы со значением шрифта
        """

        fonts = set()
        for char in line["chars"]:
            fonts.add(char["fontname"])
            line["font"] = list(fonts)
        del line["chars"]
        return line

    def extract_sections_from_pdf(self, pdf_path):
        """
        вытаскиваем главы со страниц

        pdf : pdfpluber.open объект
        """

        sections = []
        current_header = None
        current_content = []
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:

                lines = page.extract_text_lines()
                flag_header = False
                flag_article = False

                for i, line in enumerate(lines):

                    line = self.extract_font(line)
                    # вытаскиваем главы и сопутствующие им
                    if len(line["font"]) == 1 and self.is_bold(line["font"][0]) and not line["text"].startswith(
                            "Статья") and (line["text"].startswith("Глава") or flag_header):
                        flag_header = True
                        header_text = line["text"]

                        if header_text:
                            if current_header is not None:

                                if current_content:
                                    sections.append([current_header, "".join(current_content), page.page_number])
                                    current_content = []
                                    current_header = ""
                            if current_header:
                                current_header += " " + header_text

                            else:
                                current_header = header_text

                        else:
                            line_text = line["text"]

                            current_content.append(line_text)

                    # помечаем статьи(subchapter-ы)
                    elif len(line["font"]) == 1 and self.is_bold(line["font"][0]) and (
                            line["text"].startswith("Статья") or flag_article):
                        flag_article = True
                        flag_header = False
                        if line["text"].startswith("Статья"):
                            line_text = "<start_subchapter>" + line["text"]

                        else:
                            line_text = line["text"]
                        if current_header is None:

                            if sections:
                                last_header, last_content, _ = sections.pop()

                                if isinstance(last_content, str):
                                    sections.append([last_header, last_content + ' ' + line_text, page.page_number])
                                else:
                                    sections.append(
                                        [last_header, " ".join(last_content) + ' ' + line_text, page.page_number])

                            else:
                                sections.append(['Start_text', line_text, line_text.page_number])
                        else:
                            current_content.append(line_text)
                    else:
                        # Обычный контент
                        flag_header = False
                        if flag_article:
                            line_text = "<end_subchapter>" + line["text"]
                            flag_article = False
                        else:
                            line_text = line["text"]
                        if current_header is None:
                            # Start text для тексто до чаптеров
                            if sections:

                                last_header, last_content, _ = sections.pop()

                                if isinstance(last_content, str):
                                    sections.append([last_header, last_content + ' ' + line_text, page.page_number])
                                else:
                                    sections.append(
                                        [last_header, " ".join(last_content) + ' ' + line_text, page.page_number])

                            else:
                                sections.append(['Start_text', line_text, page.page_number])
                        else:
                            current_content.append(line_text)

                # Конец страницы
                if current_header and current_content:
                    sections.append([current_header, "".join(current_content), page.page_number])
                    current_header = None
                    current_content = []

        # Добавляем оставшееся
        if current_header and current_content:
            sections.append([current_header, "".join(current_content), page.page_number])
        pdf.close()
        return sections

    def split_text_to_subsections(self, text):
        """
        Разделение текста на заголовки, подзаголовки и текст с использованием регулярных выражений.

        :param document: dict, входной текстовый документ в формате JSON.
        """
        elements = []
        buffer = []
        current_subchapter = None
        structural_chunk = []
        in_subchapter = False

        # разбиваем по статьям
        parts = re.split(r'(<start_subchapter>|<end_subchapter>)', text)

        for part in parts:
            part = part.strip()
            if not part:
                continue
            if part == '<start_subchapter>':
                if current_subchapter is None and buffer:

                    elements.append({
                        'subchapter_title': None,
                        'structural_chunk': ' '.join(buffer).strip()
                    })
                    buffer = []
                elif current_subchapter is not None:

                    elements.append({
                        'subchapter_title': current_subchapter,
                        'structural_chunk': ' '.join(structural_chunk).strip()
                    })
                    structural_chunk = []
                in_subchapter = True
            elif part == '<end_subchapter>':
                in_subchapter = False
                current_subchapter = ' '.join(buffer).strip()
                buffer = []
            else:
                if in_subchapter:
                    buffer.append(part)
                else:
                    structural_chunk.append(part)

        if current_subchapter is not None:
            elements.append({
                'subchapter_title': current_subchapter,
                'structural_chunk': ' '.join(structural_chunk).strip()
            })

        elif buffer or structural_chunk:
            elements.append({
                'subchapter_title': None,
                'structural_chunk': ' '.join(buffer + structural_chunk).strip()
            })

        return elements

    def subsplits(self, text):

        def find_nth_overlapping(haystack, needle, n):
            start = haystack.find(needle)
            while start >= 0 and n > 1:
                start = haystack.find(needle, start + 1)
                n -= 1
            return start

        # убираем повторяющиеся куски в начале и конце страницы и лишние пробелы
        text = re.sub(
            self.subst1,
            '', text)
        text = re.sub(
            self.subst2,
            '', text)
        text = re.sub("  ", "", text)
        final = []

        # я честно не знаюю как сократить количество вложенности здесь,
        # скрипт нужен для одного документа, думаю и так сойдет
        if re.findall(self.first_findall, text):
            # расчанковываем по 1.
            chunks = [x for x in re.split(self.first_chunks, text) if x]
            # по возможности делам конструкции вроде 1.Первый уровень:1)второй уровень:а)третий уровень
            for chunk1 in chunks:
                if len(re.split(self.second_split, chunk1)) > 1:
                    # расчанвоываем по 1)
                    for chunk2 in re.split(self.second_split, chunk1):
                        if len(re.split(self.third_split, chunk2)) > 1:
                            # расчанковываем по а)
                            chunk3 = re.split(self.third_split, chunk2)
                            for chunk4 in chunk3[1:]:
                                final.append(chunk1[0:chunk1.find(":") + 2] + chunk2[
                                                                              chunk1.find(":") + 2:find_nth_overlapping(
                                                                                  chunk2, ":", 2) + 2] + chunk4)
                        else:

                            final.append(chunk1[0:chunk1.find(":") + 2] + chunk2)
                else:
                    final.append(chunk1)
        else:

            chunks = re.split(self.else_split, text)
            if len(chunks) > 1 and chunks[0].endswith(":"):
                chunks1 = [chunks[0] + " " + ch for ch in chunks[1:]]
                final.extend(chunks1)
            else:
                final.extend(chunks)

        res = []
        for chunk in final:
            if count_tokens(chunk)<1500:
                res.append(chunk)
                continue


            splits = self.splitter.split_text_by_points(text = chunk)
            for sp in splits:
                res.append(sp)
        return res

    def preprocess_doc(self, pdf_path, out_name):
        sec = self.extract_sections_from_pdf(pdf_path)
        sections = []

        for i,sp in enumerate(sec):
            chunks = self.split_text_to_subsections(sp[1])
            for j in chunks:
                el = {}
                el["chapter_title"] = sp[0]
                el["subchapter_title"] = j["subchapter_title"]
                el["structural_chunk"] = j["structural_chunk"]
                el["page_num"] = sp[2]
                sections.append(el)

        chunked = []
        for sp in sections:

            chunks = self.subsplits(sp["structural_chunk"])
            for j in chunks:
                el = {}
                el["chapter_title"] = sp["chapter_title"]
                el["subchapter_title"] = sp["subchapter_title"]
                el["structural_chunk"] = j
                el["page_num"] = sp["page_num"]
                el["doc_name"] = pdf_path.split(".pdf")[0].split("/")[-1]
                chunked.append(el)

        out = open(out_name, "w", encoding='utf8')
        json.dump(chunked, out, ensure_ascii=False)
        out.close()

if __name__ =="__main__":
    chunk = chunk_codex("chunked_pdf7")
    chunk.preprocess_doc("pdf_docs/Кодекс_от_29_12_2004_N_190_ФЗ_Градостроительный_кодекс_Российской.pdf","chunked_pdf7/Кодекс_от_29_12_2004_N_190_ФЗ_Градостроительный_кодекс_Российской.json")
