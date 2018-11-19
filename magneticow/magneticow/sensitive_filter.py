#!/usr/bin/env python
# -*- coding:utf-8 -*-
from collections import defaultdict
import re
try:
    from magneticow import pinyin
except:
    import pinyin

class DFAFilter():

    '''Filter Messages from keywords

    Use DFA to keep algorithm perform constantly

    >>> f = DFAFilter()
    >>> f.add("sexy")
    >>> f.filter("hello sexy baby")
    hello **** baby
    '''

    def __init__(self):
        self.keyword_chains = {}
        self.delimit = '\x00'

        self.add('.com')
        self.add('.cc')
        self.add('.cn')

    def add(self, keyword):
        keyword = keyword.lower()
        chars = keyword.strip()
        if not chars:
            return
        level = self.keyword_chains
        for i in range(len(chars)):
            if chars[i] in level:
                level = level[chars[i]]
            else:
                if not isinstance(level, dict):
                    break
                for j in range(i, len(chars)):
                    level[chars[j]] = {}
                    last_level, last_char = level, chars[j]
                    level = level[chars[j]]
                last_level[last_char] = {self.delimit: 0}
                break
        if i == len(chars) - 1:
            level[self.delimit] = 0

    def parse(self, path, cstr=None):
        key_word = open(path, 'r').read().split(cstr)

        for word in key_word:
            self.add(word)

    def filter(self, message):
        message = message.lower()
        ret = []
        start = 0
        while start < len(message):
            level = self.keyword_chains
            step_ins, char_ins = 0, ''
            for char in message[start:]:
                if char in level:
                    char_ins = char_ins + char
                    step_ins += 1
                    if self.delimit not in level[char]:
                        level = level[char]
                    #.com, .cn, .cc
                    elif char_ins[:2] == '.c':
                        #域名都转空
                        if ret[-1].isalpha():
                            #域名前缀也删了
                            del ret[-1]

                        start += step_ins - 1
                        break
                    else:
                        piny = pinyin.convert_to_pinyin(char_ins)
                        if char_ins in piny:
                            piny = '*' * step_ins
                        ret.append(" '"+piny+"' ")
                        start += step_ins - 1
                        break
                else:
                    ret.append(message[start])
                    break
            else:
                ret.append(message[start])
            start += 1

        return ''.join(ret)


def test_first_character():
    gfw = DFAFilter()
    gfw.add("1989年")
    assert gfw.filter("1989") == "1989"


if __name__ == "__main__":
    import time
    t = time.time()
    gfw = DFAFilter()
    gfw.parse("./data/色情类.txt", ',')
    #gfw.parse("./data/政治类.txt", ',')
    #gfw.parse("./data/dirty.txt", ',')
    print(time.time() - t)
    t = time.time()
    print(gfw.filter("甜心一晚干一次要2000真是贵，但是nèn abc.com bī 大奶都很粉嫩也是很值得 土豪狂刷了几千块礼物和极品美女主播网草高科技炮机 王三哥实力一等一看上的美女没有一个列外，今天干空姐我来拍视频分享"))
    print(gfw.filter("针孔摄像机 我操操操"))
    print(gfw.filter("售假人民币 我操操操"))
    print(time.time() - t)

    test_first_character()
