
import os
import torch
# from texify.inference import batch_inference
# from texify.model.model import load_model
# from texify.model.processor import load_processor

device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
class ImageProcessor:

    def __init__(self,out_dir, ocr = False, extract_images = False):

        self.out_dir = out_dir
        self.ocr = ocr

        if ocr:

            self.model = load_model().to(device)
            self.processor = load_processor()

        self.extract_images = extract_images


    def ocr_image(self, image, page) -> str:
        """
        прогоняет texify на картинке
        :param image: dict из pdfplumber.images
        :param page: pdfplumber.Page
        :return:
        """
        image_bbox = (image['x0'], page.height - image['y1'], image['x1'], page.height - image['y0'])
        cropped_page = page.crop(image_bbox)
        image_obj = cropped_page.to_image(resolution=100)
        results = batch_inference([image_obj.original], self.model, self.processor, temperature=0.01)
        # print(results[0])
        return results[0]


    def find_nearest_left_element(self, current_element: list, elements: list) -> int:
        x0_current = current_element[0]
        target = x0_current + 1

        left, right = 0, len(elements)
        while left < right:
            mid = (left + right) // 2
            if elements[mid] <= target:
                left = mid + 1
            else:
                right = mid
        return left

    def insert_char(self, original: str, pos: int, char: str) -> str:
        """
        Вставляет символ в позицию `pos` строки `original`, игнорируя ВСЕ пробелы.

        :param original: Исходная строка (может содержать пробелы).
        :param pos: Позиция вставки (0 ≤ pos ≤ длина строки без пробелов).
        :param char: Символ для вставки.
        :return: Новая строка с вставленным символом.
        """
        # Удаляем все пробелы для проверки позиции
        stripped = original.replace(" ", "")
        if pos > len(stripped):
            pos = len(stripped)

        current_pos = 0  # Текущая позиция в строке без пробелов
        insert_idx = 0  # Индекс вставки в оригинальной строке

        for i, c in enumerate(original):
            if c != " ":
                if current_pos == pos:
                    insert_idx = i
                    break
                current_pos += 1
        else:
            # Вставка в конец, если pos == len(stripped)
            insert_idx = len(original)

        if (insert_idx == 0 or insert_idx == len(original)) or (
                original[insert_idx - 1] == " " or original[:insert_idx + 1] == 1):
            return original[:insert_idx] + char + original[insert_idx:]

        else:
            return original + char

    def extract_page_image(self, page, pdf_name: str) -> None:
        """вытаскивает страницу с картинкой в png"""

        dir_name = f"{self.out_dir}/{pdf_name.split('.pdf')[0]}"
        os.makedirs(dir_name, exist_ok=True)
        pg_img = page.to_image()
        if not os.path.isfile(f"{dir_name}/{page.page_number}.png"):
            pg_img.save(f"{dir_name}/{page.page_number}.png")

    def not_within_bboxes(self, obj, bboxes: list) -> bool:
        """
        проверка на вхождение в bbox(используюся на чек с таблицей
        :param obj: объект который проверяется на вхождение в ббоксы
        :param bboxes: ббоксы вхождение в которые проверяется
        :return:
        """

        def obj_in_bbox(_bbox):
            v_mid = (obj["top"] + obj["bottom"]) / 2
            h_mid = (obj["x0"] + obj["x1"]) / 2
            x0, top, x1, bottom = _bbox
            return (h_mid >= x0) and (h_mid < x1) and (v_mid >= top) and (v_mid < bottom)

        return not any(obj_in_bbox(__bbox) for __bbox in bboxes)

    def process_images(self, page):
        """
        полный пайплайн обработки изображений.
        :param page: pdflumber.page
        :return: спиок линий на странице со вставленными картинками
        """

        #не берем картинки в таблицах и линии в таблицах
        tables_bboxes = [table.bbox for table in page.find_tables()]
        lines = page.filter(lambda x: self.not_within_bboxes(x, tables_bboxes)).extract_text_lines()
        imgs = page.images


        sdvig = 0
        i_prev = -1
        for num_img, img in enumerate(imgs):
            if self.extract_images:
                self.extract_page_image(page,)


            # добавление point маркеров списков
            if img["stream"]["Width"] == 12 and img["stream"]["Height"] == 12 and img["stream"][
                'BitsPerComponent'] == 8 and img["stream"]['Length'] == 26:
                for i, line in enumerate(lines):

                    if line["top"] + 1 > img["top"] and line["bottom"] - 3 < img["bottom"]:
                        lines[i]["text"] = "<lists_point> " + lines[i]["text"]

            #вставка картинок
            elif img["height"] > 15 or img["width"] > 15:
                if lines:
                    img_bottom = img["bottom"]
                    closest_idx = None
                    for idx, line in enumerate(lines):
                        if line["bottom"] >= img_bottom:
                            closest_idx = idx
                            break

                    # Вставка тега изображения
                    if closest_idx is not None:

                        # Вставляем тег ПЕРЕД ближайшей нижней линией
                        d_hat = (img["x0"], img["x1"], img["y0"], img["y1"])
                        xs = [x["x1"] for x in lines[closest_idx]["chars"]]
                        if closest_idx != i_prev:
                            sdvig = 0

                        n_e = self.find_nearest_left_element(d_hat, xs) + sdvig
                        lines[closest_idx]["text"] = self.insert_char(lines[closest_idx]["text"], n_e,
                                                                      f"<img_{page.page_number}_{num_img}>")

                        sdvig += len(f"<img_{page.page_number}_{num_img}>")
                        i_prev = closest_idx
                    else:
                        # Если все линии выше изображения, добавляем в конец

                        lines.insert(0, {
                            "text": f"<img_{page.page_number}_{num_img}>",
                            "top": img["top"],
                            "bottom": img_bottom,
                            "chars": [{"x1": img["x1"], "fontname": "normal"}]
                        })
                else:
                    lines = [{"text": f"<img_{page.page_number}_{num_img}>", "bottom": img["bottom"],"top":img["top"],
                              "chars": [{"x1": 0, "fontname": "normal"}]}]
            elif self.ocr:
                ocr_res = self.ocr_image(img, page)
                # пока работа только со степенями и похожими
                print(ocr_res)
                if ocr_res.replace("$", "").isdigit():
                    image_dict = {"ocr": ocr_res, "page_height": page.height,
                                  "page_width": page.width, "x0": img["x0"],
                                  "x1": img["x1"], "y0": img["y0"], "y1": img["y1"], "top": img["top"],
                                  "bottom": img["bottom"]}
                    xs = []
                    for i, line in enumerate(lines):
                        if line["top"] + 1 > image_dict["top"] and line["bottom"] - 1 < image_dict["bottom"]:
                            for char in line["chars"]:
                                xs.append(char["x1"])
                            break

                    d_hat = (image_dict["x0"], image_dict["x1"], image_dict["y0"], image_dict["y1"])
                    if i != i_prev:
                        sdvig = 0
                    n_e = self.find_nearest_left_element(d_hat, xs) + sdvig
                    lines[i]["text"] = self.insert_char(lines[i]["text"], lines[i]["text"].strip(), n_e,
                                                        image_dict["ocr"].replace("$", "").strip())


                    sdvig += len(image_dict["ocr"].replace("$", "").strip())

                    print("ocr: ", image_dict["ocr"].replace("$", ""))
                    print("sdvig: ", sdvig)

                    i_prev = i



        return lines


if __name__ == "__main__":
    proc = ImageProcessor(out_dir="/chunked_pdf7")
    import pdfplumber

    doc = pdfplumber.open("pdf_docs/СН 484-76 Инструкция по инженерным изысканиям в горных выработках предназначаемых для размещения объектов народного хозяйства.pdf")
    pg = doc.pages[17]
    imgs = pg.images[1]
    print(proc.ocr_image(imgs,pg))