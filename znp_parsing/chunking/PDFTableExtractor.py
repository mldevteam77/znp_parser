import pdfplumber
import pandas as pd

import logging
import numpy as np

#для фильтрации странных ворниногов pdfplumber-а
logging.disable(logging.WARNING)

class PDFTableExtractor:

    """
    Класс вытаскивания таблиц из pdf-ки

    """
    def __init__(self):

        self.previous_table_bbox = None
        self.page_height = None
        self.previous_table_headers = None
        self.results = []

    def extract_text_and_tables(self, page):

        """
        вытаскив
        :param page: pdfplumber.Page
        :return: таблицы(строчки), bbox-ы таблиц
        """
        tables = page.extract_tables()
        extracted_tables = page.find_tables()
        table_bboxes = (
            [table.bbox for table in extracted_tables] if extracted_tables else []
        )
        return tables, table_bboxes

    def check_if_continuation(self,table_bboxes ,page):
        """
        Проверяет, продолжение ли таблица другой таблицы
        :param table_bboxes: bbox таблицы, x0,y0,x1,y1
        :param page: pdfplumber.Page
        :return: bool, таблица или нет
        """

        if not table_bboxes or not self.previous_table_bbox:
            return False

        first_table_bbox = table_bboxes[0]

        prev_x0, prev_y0, prev_x1, prev_y1 = self.previous_table_bbox


        # проверяем что таблицы y0 меньше 0.1 высоты таблицы
        # там y0 считается с начала
        is_continuation = first_table_bbox[1] < page.height * 0.1

        # также проверяем что прмерно одинаковая ширина таблиц
        same_width = abs((first_table_bbox[2] - first_table_bbox[0]) - (prev_x1 - prev_x0)) < 10
        #и что таблица на предыдущей странице - последняя
        last_table_page_ends = prev_y1 > page.height*0.89

        return is_continuation if same_width and last_table_page_ends else False

    def table_to_dataframe(self, table, is_continuation):
        """
        перегон таблицы в датафрейм или строку
        :param table:
        :param is_continuation:
        :return:
        """
        if is_continuation and self.previous_table_headers:
            # если таблица продолжение

            if len(self.previous_table_headers) == np.array(table).shape[1]:
                # если сходятся размерности, возвращаем продолжение с заголовками предыдущей таблицы

                return pd.DataFrame(table, columns=self.previous_table_headers)
            else:
                # иначе возвращаем в виде markdown строки
                df = pd.DataFrame(table)
                md = self.dataframe_to_markdown(df)

                return md

        else:
            # просто возвращем датафрем с таблицей
            self.previous_table_headers = table[0]
            return pd.DataFrame(table[1:], columns=table[0])


    def dataframe_to_markdown(self, df: pd.DataFrame) -> str:
        """
        Преобразует DataFrame в Markdown-таблицу.
        Сначала пытается использовать встроенный метод to_markdown (потребуется tabulate),
        если не удаётся, то использует собственную реализацию.
        """
        try:
            markdown_table = df.to_markdown(index=False, tablefmt="github")
            lines = markdown_table.split('\n')
            body_lines = lines[1:] if len(lines) >= 2 else []

            return '\n'.join(body_lines)

        except ImportError:

            rows = []
            for row in df.values:
                row_str = ["" if pd.isnull(cell) else str(cell) for cell in row]
                rows.append("| " + " | ".join(row_str) + " |")
            return "\n".join(rows)

    def format_table_output(self, df):

        """
        разбиваем датафрейм на чанки
        :param df:
        :return:
        """
        table_output = []
        if isinstance(df,str):
            # если маркдаун-строка - не делаем ничего
            return df
        else:
            # разбиваем по строчкна в формат Колонка значение строки
            for index, row in df.iterrows():
                row_output = []
                for col, val in row.items():
                    row_output.append(f'Колонка "{col}": значение строки "{val}";')
                table_output.append( " ".join(row_output))
        return table_output

    def process_page(self,page):

        """
        обрабатываем страницу
        :param page:
        :return:
        """

        results = []
        table_num = 1

        tables, table_bboxes = self.extract_text_and_tables(page)
        if not table_bboxes:
            self.previous_table_bbox = None
            self.previous_table_headers = None
            return []


        for i, bbox in enumerate(table_bboxes):
            is_continuation = i == 0 and self.check_if_continuation(table_bboxes,page)
            table = tables[i] if i < len(tables) else None

            if not table:
                continue

            df = self.table_to_dataframe(table, is_continuation)
            results.append({"content": self.format_table_output(df), "coords": table_bboxes[0]})
            table_num+=1


        self.previous_table_bbox = table_bboxes[-1]

        return results


def main():
    import os
    os.listdir("Docs")
    # pdf_file = "pdf_docs/РД 31.74.09-96 Нормы на морские дноуглубительные работы.pdf"
    #pdf_file = "pdf_docs/СП 42-101-2003 Общие положения по проектированию и строительству газораспределительных систем из металлических и полиэтиленовых труб.pdf"
    # pdf_file = "pdf_docs/РД 05-448-02 Инструкция по централизованному контролю и управлению пожарным водоснабжением угольных шахт.pdf"
    pdf_file = "pdf_docs/Приказ-Ростехнадзора-от-08.12.2020-N-505-Об-утверждении-федеральных-норм-и-правил-в-области.pdf"
    output_file = "result.json"
    extractor = PDFTableExtractor()
    pg = pdfplumber.open(pdf_file).pages[25]
    print(extractor.process_page(pg))



if __name__ == "__main__":
    main()



