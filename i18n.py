import config
import json

langfile = json.load(open('i18n/{0}.json'.format(config.LANG)))


def _(string):
    if config.LANG is False:
        return string
    else:
        return langfile.get(string, string)
