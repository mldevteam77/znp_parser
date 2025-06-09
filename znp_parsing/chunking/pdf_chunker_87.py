
import regex as re
import json
import pdfplumber
from chunkers.ImageProcessor import ImageProcessor
from TokenCounter import count_tokens


class chunk_eighty_seven:
    def __init__(self, out_dir):
        self.out_dir = out_dir
        self.regex_split_subchapters = re.compile(r'(<sub_chapter>)((?:[A-ZА-Я]\.\d{1,2}(?:\.\d{1,4})*|\d{1,4}(?:\.\d{1,4})*)\.?(?=\s|$))')
        self.subsection_pattern = re.compile(
            r'(?<!\S)([а-я]|\d{1,2}(?:_\d+)?)\)\s+((?:(?!\s+([а-я]|\d{1,2}(?:_\d+)?)\)).)+)',re.DOTALL | re.IGNORECASE)
        self.regex_section = re.compile(
            r'(?<!\S)(?:[A-ZА-Я]\.\d{1,2}(?:\.\d{1,}){0,4}|\d{1,4}(?:\.\d{1,4}){0,4})(?:\.|(?<!\.)(?!\S)(?!\s*-))(?!.*\s*г\.)|(?<!\S)(?:[A-ZА-Я]\.\d{1,2}(?:\.\d{1,2}){0,4}|\d{1,4}(?:\.\d{1,4}){0,4})(?!\S)(?!\s*-)(?!.*\s*г\.)')

        self.text_part_marker = "в текстовой части"
        self.graphic_part_marker = "в графической части"
        self.image_proc = ImageProcessor(out_dir)

    def split_by_semicolumn(self,text,max_len=1500,min_len=500):

        sentences = [x for x in text.split(";")]
        result = []
        current_chunk = []
        current_length = 0

        for sentence in sentences:
            sentence_len = len(sentence)

            # Проверяем, можно ли добавить предложение без превышения max_len
            if current_length + sentence_len <= max_len:
                current_chunk.append(sentence)
                current_length += sentence_len
            else:
                # Если текущий фрагмент слишком короткий, объединяем принудительно
                if current_length < min_len:
                    current_chunk.append(sentence)
                    result.append(' '.join(current_chunk).strip())
                    current_chunk = []
                    current_length = 0
                else:
                    # Сохраняем текущий фрагмент и начинаем новый
                    result.append(' '.join(current_chunk).strip())
                    current_chunk = [sentence]
                    current_length = sentence_len

        # Добавляем последний накопленный фрагмент
        if current_chunk:
            result.append(' '.join(current_chunk).strip())

        return result


    def split_text_to_subsections(self, text):
        """
        Разделение текста на заголовки, подзаголовки и текст с использованием регулярных выражений.

        :param document: dict, входной текстовый документ в формате JSON.
        :param regex: str, регулярное выражение для поиска подзаголовков.
        :return: dict, структурированный результат.
        """

        subsections = []
        matches = list(re.finditer(self.regex_split_subchapters, text))

        if not matches:
            return text.strip()

        for i, match in enumerate(matches):
            start = match.start()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            subtitle = match.group(2)
            subsection_text = text[start + len(match.group(1) + subtitle):end].strip()
            if len(re.findall(self.subsection_pattern,subsection_text))>1:

                # обычного сплиттинга хватает
                splits = self.splitting(subsection_text)
                for sp in splits:

                    if count_tokens(sp)<1500:
                        if len(sp) == 0:
                            continue
                        el = {}
                        el["subchapter_title"] = subtitle
                        el["structural_chunk"] = sp
                        subsections.append(el)
                    else:
                        sp_dop = self.split_by_semicolumn(sp)
                        for s in sp_dop:
                            el = {}
                            el["subchapter_title"] = subtitle
                            el["structural_chunk"] = s
                            subsections.append(el)
            else:
                if count_tokens(subsection_text) < 1500:
                    el = {}
                    el["subchapter_title"] = subtitle
                    el["structural_chunk"] = subsection_text
                    subsections.append(el)
                else:
                    sp_dop = self.split_by_semicolumn(subsection_text)
                    for s in sp_dop:
                        el = {}
                        el["subchapter_title"] = subtitle
                        el["structural_chunk"] = s
                        subsections.append(el)

        return subsections

    def splitting(self, text):
        r"""
        Разделяет входной текст на три части, если найдены маркеры "в текстовой части" и "в графической части".
        Если маркеры отсутствуют, обрабатывает весь текст как одну часть и делит его на подразделы.

        Делит текст на подразделы, соответствующие шаблону '\n[a-я]\) .+?(?=\n[a-я]\)|$)'.
        Компилирует каждый подраздел с частью1 + ("в текстовой части" или "в графической части", если маркеры есть) + текст подраздела.

        Учитывает ситуации:
        1. Текст содержит "в текстовой части" и "в графической части".
        2. Текст содержит "в текстовой части", но отсутствует "в графической части".
        3. Отсутствует "в текстовой части", но есть "в графической части"
        4. Маркеры отсутствуют.

        Аргументы:
            text (str): Входной текст для разделения.

        Возвращает:
            list: Список строк, объединяющих часть1 и подразделы из частей текста.
        """

        # Определение точек разделения


        # Поиск индексов маркеров
        text_part_index = text.find(self.text_part_marker)
        graphic_part_index = text.find(self.graphic_part_marker)

        # Разделение текста на части
        # Если отсутствует упоминание и текстовой и графической частей
        if text_part_index == -1 and graphic_part_index == -1:
            # Если маркеры отсутствуют, берется текст до второго \n
            # part1 = text.strip()
            part1 = re.split(self.subsection_pattern,text)[0].strip()
            part2 = ""
            part3 = ""

        # если отсутствует текстовая часть, а есть только графическая
        elif text_part_index == -1 and graphic_part_index != -1:
            part1 = re.sub(':', '', text.split('\n')[0].strip())
            part2 = text[:graphic_part_index].strip()
            part3 = text[graphic_part_index:].strip() if graphic_part_index != -1 else ""

        # Если отсутствует обе части
        else:
            part1 = text[:text_part_index].strip() if text_part_index != -1 else text[:graphic_part_index].strip()
            part2 = text[text_part_index:graphic_part_index].strip() if graphic_part_index != -1 and text_part_index != -1 else text[text_part_index:].strip() if text_part_index != -1 else ""
            part3 = text[graphic_part_index:].strip() if graphic_part_index != -1 else ""

        # Регулярное выражение для поиска подразделов


        # Вспомогательная функция для обработки подразделов
        def process_subsections(base_part, part_text, marker):
            matches = self.subsection_pattern.findall(part_text)

            combined_substrings = [
                re.sub(r'\s{2,}', ' ',
                       re.sub('\n', ' ', f"{base_part.strip()} {marker} {match[0]}) {match[1].strip()}")) for match in
                matches
            ]
            return combined_substrings

        # Обработка частей
        if text_part_index == -1 and graphic_part_index == -1:

            # Если маркеры отсутствуют
            result = process_subsections(part1, text.strip(), "")

        elif text_part_index == -1 and graphic_part_index != -1:
            part2_substrings = process_subsections(part1, part2, "") if part2 else []
            part3_substrings = process_subsections(part1, part3,  self.graphic_part_marker) if part3 else []
            result = part2_substrings + part3_substrings

        else:
            part2_substrings = process_subsections(part1, part2, self.text_part_marker) if part2 else []
            part3_substrings = process_subsections(part1, part3, self.graphic_part_marker) if part3 else []
            result = part2_substrings + part3_substrings



        if result:

            return result
        else:

            return [text.strip()]

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

    def extract_sections_from_pdf(self, pdf_path: str) -> list:
        """
        вытаскиваем главы со страниц

        pdf : строка пути к пдфк
        """

        sections = []
        current_header = None
        current_content = []

        # паттер для добавления метки сабчаптера, повышает точность извлечения

        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:

                lines = self.image_proc.process_images(page)
                for line in lines:

                    # проверка на хэддер(bold текст или нет)

                    line = self.extract_font(line)
                    line_bold = len(line["font"]) == 1 and self.is_bold(line["font"][0])

                    if line_bold:
                        header_text = line["text"]
                        if header_text:
                            if current_header is not None:
                                # добавляем предыдущую если есть контент
                                if current_content:
                                    sections.append([current_header, "".join(current_content),page.page_number])
                                    current_content = []
                                    current_header = ""
                            if current_header:
                                current_header += " " + header_text
                            else:
                                current_header = header_text
                        else:
                            # мерджим
                            line_text = line["text"]
                            # добавления маркера subchapter-А
                            if re.match(self.regex_section, line_text) and len(line_text) > 3:

                                line_text = "<sub_chapter>" + line_text
                            current_content.append(line_text)
                    else:
                        # Обычный контент
                        line_text = line["text"]

                        if re.match(self.regex_section, line_text) and len(line_text) > 3:
                            line_text = "<sub_chapter>" + line_text

                        if current_header is None:

                            if sections:

                                last_header, last_content, _ = sections.pop()

                                if isinstance(last_content, str):
                                    sections.append([last_header, last_content + ' ' + line_text, page.page_number])
                                else:
                                    sections.append([last_header, " ".join(last_content) + ' ' + line_text,page.page_number])
                            else:
                                # Start text для текстов до чаптеров
                                sections.append(['Start_text', line_text, page.page_number])
                        else:
                            current_content.append(line_text)

                # Конец страницы
                if current_header and current_content:
                    sections.append([current_header, " ".join(current_content),page.page_number])
                    current_header = None
                    current_content = []

        # Добавляем оставшееся
        if current_header and current_content:
            sections.append([current_header, " ".join(current_content),[page.page_number]])
        pdf.close()
        return sections

    def preprocess_doc(self, pdf_name: str, out_name: str = "out.json") -> None:
        """
        Полный процессинг дока в json
        """

        splited_paragraphs = self.extract_sections_from_pdf(pdf_name)
        preprocessed_json = []
        for i, content in enumerate(splited_paragraphs):
            splited_paragraphs[i][1] = self.split_text_to_subsections(splited_paragraphs[i][1])
            if isinstance(splited_paragraphs[i][1], str):
                preprocessed_json.append({"chapter_title": splited_paragraphs[i][0],
                                          "subchapter_title": "",
                                          "structural_chunk": splited_paragraphs[i][1].replace("<sub_chapter>",""),
                                          "page_num":splited_paragraphs[i][2],
                                          "type":"text",
                                          "doc_name": pdf_name.split(".pdf")[0]})

            else:
                for j, dct in enumerate(splited_paragraphs[i][1]):
                    preprocessed_json.append({"chapter_title": splited_paragraphs[i][0],
                                              "subchapter_title": dct["subchapter_title"],
                                              "structural_chunk": dct["structural_chunk"].replace("<sub_chapter>",""),
                                              "page_num":splited_paragraphs[i][2],
                                              "type": "text",
                                              "doc_name": pdf_name.split(".pdf")[0].split("/")[-1]})

        out = open(out_name, "w", encoding='utf8')
        json.dump(preprocessed_json, out, ensure_ascii=False)
        out.close()

if __name__ == "__main__":
    chunk = chunk_eighty_seven("chunked_pdf7")
    chunk.preprocess_doc("pdf_docs/Постановление_Правительства_РФ_от_16_02_2008_N_87_О_составе_разделов.pdf", "chunked_pdf7/Постановление_Правительства_РФ_от_16_02_2008_N_87_О_составе_разделов.json")