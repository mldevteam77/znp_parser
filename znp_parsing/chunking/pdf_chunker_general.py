
from TokenCounter import count_tokens
from TextSplitter import TextSplitter
from chunkers.ImageProcessor import ImageProcessor
from PDFTableExtractor import PDFTableExtractor
import regex as re
import json
import pdfplumber


class pdf_chunker:

    def __init__(self, out_dir="chunked_pdf", extract_images=False, ocr=False):
        self.out_dir = out_dir

        self.regex_subsections = re.compile(
            r'(<sub_chapter>)((?:[A-ZА-Я]\.\d{1,2}(?:\.\d{1,4})*|\d{1,4}(?:\.\d{1,4})*)\.?(?=\s|$))')
        self.pattern_subsplitting = re.compile(
            r"(?<!\b\p{L}\.)(?<=[.:;])(?![a-zA-Zа-яА-Я0-9])(?!\s*(?:т\.д\.|д\.р\.|т\.п\.| др\.))")
        self.gost_starting_line = re.compile(
            r"^(В настоящем своде правил использованы нормативные ссылки на следующие документы:|В настоящей инструкции использованы ссылки на следующие нормативные документы:)",
            flags=re.IGNORECASE)
        self.regex_section = re.compile(
            r'(?<!\S)(?:[A-ZА-Я]\.\d{1,2}(?:\.\d{1,}){0,4}|\d{1,4}(?:\.\d{1,4}){0,4})(?:\.|(?<!\.)(?!\S)(?!\s*-))(?!.*\s*г\.)|(?<!\S)(?:[A-ZА-Я]\.\d{1,2}(?:\.\d{1,2}){0,4}|\d{1,4}(?:\.\d{1,4}){0,4})(?!\S)(?!\s*-)(?!.*\s*г\.)')
        self.splitter = TextSplitter()
        self.image_proc = ImageProcessor(out_dir, ocr, extract_images)
        self.table_proc = PDFTableExtractor()

    def split_subsections(self, text, subtitle):
        subsections = []
        if count_tokens(text) > 1500:

            if re.match(self.gost_starting_line, text.strip()):
                # проверяем на список ГОСТов
                splits = self.splitter.split_GOST(text)
                for sp in splits:
                    if len(sp) == 0:
                        continue
                    el = {}
                    el["subchapter_title"] = subtitle
                    el["structural_chunk"] = sp
                    subsections.append(el)

            elif len(re.findall(self.pattern_subsplitting, text)[:-1]) > 1:
                # Доразбиение по правилам
                splits = self.splitter.splitting(text)
                for sp in splits:
                    if count_tokens(sp) < 1500:
                        if len(sp) == 0:
                            continue
                        el = {}
                        el["subchapter_title"] = subtitle
                        el["structural_chunk"] = sp
                        subsections.append(el)

                    else:
                        # если опять слишком длинный - разибваем по точкам
                        splits_2 = self.splitter.split_text_by_points(sp)
                        for sp2 in splits_2:
                            if count_tokens(sp2) > 2000:
                                # последнее разбиение для совсем запущенных случаем
                                splits_3 = self.splitter.final_split_for_tables(sp2)

                                for sp3 in splits_3:
                                    el = {}
                                    el["subchapter_title"] = subtitle
                                    el["structural_chunk"] = sp3
                                    subsections.append(el)
                            else:
                                el = {}
                                el["subchapter_title"] = subtitle
                                el["structural_chunk"] = sp2
                                subsections.append(el)
            else:
                # дальше в коде повторяется один алгоритм
                splits = self.splitter.split_text_by_points(text)

                for sp in splits:
                    if count_tokens(sp) > 2000:
                        splits_2 = self.splitter.final_split_for_tables(sp)

                        for sp2 in splits_2:
                            el = {}
                            el["subchapter_title"] = subtitle
                            el["structural_chunk"] = sp2
                            subsections.append(el)
                    else:
                        el = {}
                        el["subchapter_title"] = subtitle
                        el["structural_chunk"] = sp
                        subsections.append(el)

        else:
            el = {}
            el["subchapter_title"] = subtitle
            el["structural_chunk"] = text

            subsections.append(el)
        return subsections

    def split_text_to_subsections(self, text: str, type: str) -> list:
        """
        Разделение текста на заголовки, подзаголовки и текст с использованием регулярных выражений.

        :param text: строка, текст чаптера
        :return: list, разбиение на subchapter-ы
        """
        if type == "table":
            return [{'subchapter_title': "", 'structural_chunk': text}]
        text = re.sub(r'Об утверждении Федеральных норм и правил в области промышленной безопасности.*?Страница\s+\d+',
                      '', text, flags=re.DOTALL | re.IGNORECASE)
        matches_subtitle = list(re.finditer(self.regex_subsections, text))

        subsections = []
        if not matches_subtitle:
            # обработка элементов без главы

            return self.split_subsections(text, "")
        if matches_subtitle[0].start()!=0:
            subsections.extend(self.split_subsections(text[0:matches_subtitle[0].start()], ""))
        for i, match in enumerate(matches_subtitle):
            # выделение subtitle и текста
            start_subtitle = match.start()
            end_subtitle = matches_subtitle[i + 1].start() if i + 1 < len(matches_subtitle) else len(text)

            subtitle = match.group(2)
            subsection_text = text[start_subtitle + len(match.group(1) + subtitle):end_subtitle].strip()
            # дотокенизируем если длина больше 1500

            subsections.extend(self.split_subsections(subsection_text, subtitle))
        return subsections

    def is_bold(self, fontname: str) -> bool:
        """
        Проверка шрифта на жирность
        """
        return 'Bold' in fontname or 'BD' in fontname

    def extract_font(self, line: dict):
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
        Открывает пдфку и вытаскивает текст

        :param pdf_path:
        :return:
        """

        sections = []
        current_header = None
        current_header_page = None
        current_content = []
        last_valid_header = None

        active_table_header = None


        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                header_flag = True
                page_number = page.page_number
                text_lines = self.image_proc.process_images(page)
                tables = self.table_proc.process_page(page)

                all_elements = []

                for line in text_lines:
                    line = self.extract_font(line)
                    all_elements.append({
                        "type": "text",
                        "content": line,
                        "top": line["top"]
                    })

                # Таблицы
                for table in tables:
                    all_elements.append({
                        "type": "table",
                        "content": table,
                        "top": table["coords"][1]
                    })
                # отсортировали по положению на странице
                all_elements.sort(key=lambda x: x["top"])
                for element in all_elements:
                    if element["type"] == "text":
                        line = element["content"]
                        line_bold = len(line["font"]) == 1 and self.is_bold(line["font"][0])
                        line_text = line["text"].strip()

                        # добавляем сабчаптеры
                        if re.match(self.regex_section, line_text) and len(line_text) > 3 and not line_bold:
                            line_text = "<sub_chapter>" + line_text

                        if line_bold and line_text:
                            active_table_header = None
                            if current_header and current_content:
                                sections.append(
                                    [current_header, " ".join(current_content), current_header_page, "text"])

                                current_content = []

                            if header_flag:
                                current_header = current_header+ line_text if current_header else line_text
                            else:
                                current_header = line_text
                                header_flag = True

                            current_header_page = page_number
                            last_valid_header = current_header
                            last_valid_page = current_header_page

                        elif current_header:
                            current_content.append(line_text + " ")
                            header_flag = False

                        else:
                            if sections:

                                sections[-1][1] += line_text + " "

                            else:
                                sections.append(["Start_text", line_text + " ", page_number, "text"])



                    elif element["type"] == "table":
                        # Определение заголовка для таблицы
                        if active_table_header:
                            # Продолжение межстраничной таблицы
                            target_header = active_table_header
                            target_page = page_number
                        else:
                            # Новая таблица: привязка к текущему заголовку
                            target_header = current_header if current_header else last_valid_header

                            active_table_header = target_header  # Запоминаем для продолжения

                        # Добавление таблицы
                        table_data = element["content"]["content"]
                        if isinstance(table_data, str):

                            sections.append([target_header, table_data, page_number, "table"])

                        else:
                            for row in table_data:
                                sections.append([target_header, row, page_number, "table"])

                # Завершаем текущий заголовок
            if current_header and current_content:
                sections.append([current_header, "".join(current_content).strip(), current_header_page, "text"])

        return sections

    def preprocess_doc(self, pdf_name: str, out_name: str = "out.json") -> None:
        """
        Полный процессинг дока в json
        """

        splited_paragraphs = self.extract_sections_from_pdf(pdf_name)
        preprocessed_json = []
        for i, content in enumerate(splited_paragraphs):
            splited_paragraphs[i][1] = self.split_text_to_subsections(splited_paragraphs[i][1],
                                                                      splited_paragraphs[i][3])
            if isinstance(splited_paragraphs[i][1], str):

                preprocessed_json.append({"chapter_title": splited_paragraphs[i][0].replace("<sub_chapter>", ""),
                                          "subchapter_title": "",
                                          "structural_chunk": splited_paragraphs[i][1].replace("<sub_chapter>", ""),
                                          "page_num": splited_paragraphs[i][2],
                                          "type": splited_paragraphs[i][3],
                                          "doc_name": pdf_name.split(".pdf")[0]})

            else:
                for j, dct in enumerate(splited_paragraphs[i][1]):
                    #                     print(splited_paragraphs[i][1])
                    preprocessed_json.append({"chapter_title": splited_paragraphs[i][0].replace("<sub_chapter>", ""),
                                              "subchapter_title": dct["subchapter_title"],
                                              "structural_chunk": dct["structural_chunk"].replace("<sub_chapter>", ""),
                                              "page_num": splited_paragraphs[i][2],
                                              "type": splited_paragraphs[i][3],
                                              "doc_name": pdf_name.split(".pdf")[0].split("/")[-1]})
        self.table_proc = PDFTableExtractor()
        out = open(f"{self.out_dir}/{out_name}", "w", encoding='utf8')
        json.dump(preprocessed_json, out, ensure_ascii=False)
        out.close()


if __name__ =="__main__":
    chunk = pdf_chunker("chunked_pdf5", ocr= False, extract_images=False)
    # doc="РД 05-448-02 Инструкция по централизованному контролю и управлению пожарным водоснабжением угольных шахт.pdf"
    # doc = "СП 42-101-2003 Общие положения по проектированию и строительству газораспределительных систем из металлических и полиэтиленовых труб.pdf"
    # doc ="РД 31.74.09-96 Нормы на морские дноуглубительные работы.pdf"
    # doc = "Приказ-Ростехнадзора-от-08.12.2020-N-505-Об-утверждении-федеральных-норм-и-правил-в-области.pdf"
    # docs = ["РД 31.74.09-96 Нормы на морские дноуглубительные работы.pdf",
    #         "РД 153-34.0-20.507-98 Типовая инструкция по технической эксплуатации систем транспорта и распределения тепловой энергии тепловых сетей.pdf",
    #         "РД 52.04.275-89 Методические указания. Проведение изыскательских работ по оценке ветроэнергетических ресурсов для обоснования.pdf",
    #         "СН 525-80 Инструкция по технологии приготовления полимербетонов и изделий из них.pdf",
    #         "СП 234.1326000.2015 Железнодорожная автоматика и телемеханика. Правила строительства и монтажа.pdf",
    #         "СП 30.13330.2020 Внутренний водопровод и канализация зданий СНиП 2.04.01-85 с Изменениями N 1 2 3.pdf",
    #         "СП 333.1325800.2020 Информационное моделирование в строительстве. Правила формирования информационной модели объектов на различных стадиях.pdf",
    #         "СП 421.1325800.2018 Мелиоративные системы и сооружения. Правила эксплуатации.pdf",
    #         "СП 478.1325800.2019 Здания и комплексы аэровокзальные. Правила проектирования с Изменениями N 1 2.pdf",
    #         "СП 66.13330.2011 Проектирование и строительство напорных сетей водоснабжения и водоотведения с применением высокопрочных труб из чугуна.pdf"]

    doc =  "СП 308.1325800.2017 Исправительные учреждения и центры уголовно-исполнительной системы. Правила проектирования в двух частях.pdf"


    chunk.preprocess_doc(f"pdf_docs/{doc}", f"{doc.split('.pdf')[0]}.json")

