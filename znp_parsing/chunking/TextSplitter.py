import regex as re
from razdel import sentenize


class TextSplitter:
    def __init__(self):
        self.pattern = re.compile(r"(?<!\b\p{L}\.)(?<=[.:;])(?![a-zA-Zа-яА-Я0-9])(?!\s*(?:т\.д\.|д\.р\.|т\.п\.| др\.))",re.IGNORECASE)
        self.list_patterns = [
            (re.compile(r'^\s*([а-яА-Я])\)\s*', re.UNICODE), 'alpha'),
            (re.compile(r'^\s*(\d+)\)\s*', re.UNICODE), 'digit'),
            (re.compile(r'^\s*-\s*', re.UNICODE), 'dash'),
            (re.compile(r'^\s*<lists_point>\s*', re.UNICODE), 'custom')
        ]
        self.pattern_GOST = re.compile(r"(?=\bГОСТ|РД|РМГ|СНИП|РДТ|СанПиН|РТ|СП(?:\s+Р)?\s*(?:\d+[-.\s]*)+(?:[а-яa-z]{0,3})\b)")

        self.cavets_reg = re.compile(r'(?=\[\d+\])')

    def splitting(self, text):
        """
        дополнительный сплит сабчаптеров по спискам
        :param text: строка, чанк сабчаптера
        :return:
        """
        # разбиениее на предложения по .:; чтобы дальше соединять

        splits = re.split(self.pattern, text)
        # паттерны различных списков

        # на всякий случай убираем \n
        for i, split in enumerate(splits):
            splits[i] = splits[i].replace("\n", "")

            # соединение элементов по ;(признак списка)
        i = 1
        while i < len(splits):
            current = splits[i].strip()

            if current.endswith(';') and not self._get_element_type(current)[0]:

                splits[i - 1] = splits[i - 1] + splits[i]
                del splits[i]
            else:
                i += 1

        # распределение  по спискам
        list_elements = []
        for i, chunk in enumerate(splits):
            etype, value = self._get_element_type(chunk.strip())
            if etype:
                list_elements.append((i, etype, value))

        for i in reversed(range(len(list_elements) - 1)):
            curr_idx, curr_type, curr_val = list_elements[i]
            next_idx, next_type, next_val = list_elements[i + 1]

            if curr_type == next_type:
                sequence_ok = False

                if curr_type == 'alpha':
                    sequence_ok = (ord(next_val) == ord(curr_val) + 1)

                elif curr_type == 'digit':
                    sequence_ok = (next_val == curr_val + 1)

                elif curr_type in ('dash', 'custom'):
                    sequence_ok = True

                if sequence_ok:
                    merged = ''.join(splits[curr_idx:next_idx + 1])
                    splits[curr_idx] = merged
                    del splits[curr_idx + 1:next_idx + 1]

                    for j in range(i + 1, len(list_elements)):
                        list_elements[j] = (
                            list_elements[j][0] - (next_idx - curr_idx),
                            list_elements[j][1],
                            list_elements[j][2]
                        )

        # пременяем все обработочные функции
        splits = self._add_last_sent(splits)
        splits = self._add_context(splits)
        splits = self._conc_sublist(splits)
        splits = self._conc_nonlist(splits)

        return splits

    def _get_element_type(self,s):
        '''
        получение типа строки
        :param s: строка
        :return:
        '''
        for pattern, etype in self.list_patterns:
            if re.match(pattern, s):
                match = re.match(pattern, s)
                value = match.group(1).lower() if etype == 'alpha' else int(
                    match.group(1)) if etype == 'digit' else None
                return etype, value
        return None, None

    def _add_last_sent(self,splits):
        """докидывание одного дополнительного предложения заканчивающегося на точку в чанк со списками(обычно это последний элемент списка)"""
        for i, split in enumerate(splits):
            if split.endswith(";") and not self._get_element_type(splits[i + 1])[0] and splits[i + 1].endswith("."):
                splits[i] += splits[i + 1]
                del splits[i + 1]
        # соединение слишком коротких(фильтрация рандомно разделенных вещей типо дат)
        for i, split in enumerate(splits):
            if len(split) < 10:
                splits[i - 1] += splits[i]
                del splits[i]
        return splits

    def _add_context(self, splits):
        """добавление контекста из трех предлоожений до(если они не части списков)"""
        rev_splits = list(reversed(splits))
        l = []
        for i, split in enumerate(rev_splits):
            if self._get_element_type(split)[0]:
                if i < len(rev_splits) - 1 and self._get_element_type(rev_splits[i + 1])[0]:
                    continue
                else:
                    if (i + 1) < len(rev_splits):
                        rev_splits[i] = rev_splits[i + 1] + rev_splits[i]
                        l.append(i + 1)

                if i < len(rev_splits) - 2 and self._get_element_type(rev_splits[i + 2])[0]:
                    continue
                else:
                    if (i + 2) < len(rev_splits):
                        rev_splits[i] = rev_splits[i + 2] + rev_splits[i]
                        l.append(i + 2)
                if i < len(rev_splits) - 3 and self._get_element_type(rev_splits[i + 3])[0]:
                    continue
                else:
                    if (i + 3) < len(rev_splits):
                        rev_splits[i] = rev_splits[i + 3] + rev_splits[i]
                        l.append(i + 3)

        temp = []
        for i, split in enumerate(rev_splits):
            if i not in l:
                temp.append(split)

        return list(reversed(temp))

    def _conc_sublist(self,splits):
        """соединение списков с подсписками"""
        l = []
        for i, split in enumerate(splits):
            if i < len(splits) - 1 and split.endswith(":") and self._get_element_type(splits[i + 1])[0]:
                splits[i + 1] = splits[i] + splits[i + 1]

                l.append(i)
        new_splits = []
        for i, split in enumerate(splits):
            if i not in l:
                new_splits.append(split)

        return new_splits

    def _conc_nonlist(self,splits):
        """соединение одиночных не-списковых предложений"""

        l = []
        buff = ""
        for i, split in enumerate(splits):
            sp = re.split(self.pattern, split)[:-1]

            if (i + 1) < len(splits) and len(sp) == 1:
                buff += "".join(sp)
            elif (i + 1) < len(splits):

                if buff:
                    l.append(buff)
                    buff = ""
                buff += "".join(sp)
                l.append(buff)
                buff = ""
        if buff:
            l.append(buff)
        return l

    def split_GOST(self, text):
        splits = re.split(self.pattern_GOST, text)

        # Находим индекс первого элемента, который заканчивается на ":"
        for i, item in enumerate(splits):
            if item.strip().endswith(":"):
                starting = " ".join(splits[:i + 1])
                splits = splits[i + 1:]
                break
        else:
            starting = ""

        # Группируем элементы по 3
        res = []
        for i in range(0, len(splits), 3):
            group = "".join(splits[i:i + 3])
            res.append((starting + group) if starting else group)

        return res

    def split_text_by_points(self, text, min_len=200, max_len=500):
        """
        Разделяем текст на предложения с помощью razdel
        """
        sentences = [sentence.text.strip() for sentence in sentenize(text)]

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

    def final_split_for_tables(self, text, max_len=1500, min_len=500):
        """
        финальный сплит табличных данных, которые не распознались как таблицы
        Разделяются [1], X X X X, ; и просто по словам
        :param text:
        :param max_len:
        :param min_len:
        :return:
        """
        if len(re.split(self.cavets_reg, text)) > 2:
            return re.split(self.cavets_reg, text)
        elif text.find("Х Х Х Х Х") != -1:
            return text.split("Х Х Х Х Х")
        elif len(text.split(";")) > 5:
            return text.split(";")
        elif len(text.split(" - "))>5:
            return text.split(" - ")
        else:
            words = text.split(" ")
            segments = []
            current_segment = []
            current_length = 0

            for word in words:
                word_length = len(word) + 1  # +1 для пробела
                if current_length + word_length > max_len and current_length >= min_len:
                    segments.append(" ".join(current_segment))
                    current_segment = [word]
                    current_length = word_length
                else:
                    current_segment.append(word)
                    current_length += word_length

            # Добавляем последний сегмент, если он не пустой
            if current_segment:
                segments.append(" ".join(current_segment))

            return segments


