#!/usr/bin/env python3
import sys
from functools import lru_cache
from subprocess import Popen,PIPE

import threading
import time
import argparse

from elitr.onlinetextflow.events import yield_events
from elitr.onlinetextflow.textflow_protocol import *

######## Buffer

# buffer's internal data object
class Segment:
    def __init__(self, i,j,text, receive_time=None):
        self.index = i
        self.status = j-i
        self.text = text
        self.receive_time = receive_time
        # TODO: this would be helpful for some future mask-k analysis
#        self.masked_part = ""

    def out_text(self):
#        if self.masked_part:
#            return "%s+++%s" % (self.text, self.masked_part)
        return self.text

    def __repr__(self):
        d = self.__dict__.copy()
        return str(d)



class Buffer:
    def __init__(self, mask_k=0, min_status=0):
        self.buff = {}
        self.last_insert_time = None
        self.mask_k = mask_k
        self.min_status = min_status

        self.min_index = 100
        self.max_index = 0

    def mask(self, index, status, text):
        if self.mask_k == 0:
            return text
        if status-index == 1:
            toks = text.split()
            if len(toks) <= self.mask_k:
                return None
            masked_text = " ".join(toks[:-self.mask_k])
#            cropped = " ".join(toks[-self.mask_k:])
            if index in self.buff:
                s = self.buff[index]
                if s.status == status-index and s.text == masked_text:
#                    s.masked_part = cropped
                    return None
            return masked_text
        return text

    def insert(self, line, curr_time):
        '''line is 
        "100 101 I 'm going to talk today about energy, and...\n"
        we're ignoring the original timestamps, for simplicity
        '''
        (index, status), text = parse(line, types=[int, int])
        text = self.mask(index, status, text)
        if text is None:
            return
        seg = Segment(index, status, text, receive_time=curr_time)
        self.buff[index] = seg
        self.last_insert_time = curr_time
        self.max_index = index  # every insert invalidates > indeces

    def get_updates(self, from_time, min_status=None):
        if min_status is None:
            min_status = self.min_status
        updates = []
        for i in range(self.min_index, self.max_index+100,100):
            if i in self.buff:
                seg = self.buff[i]
                if seg.receive_time > from_time and seg.status >= min_status:
                    updates.append(seg)
                    if seg.status == 100:
                        self.min_index = seg.index
                        del self.buff[i]
        return updates


class Translator:
    def __init__(self, cmd, args):
        self.mtcmd = " ".join(cmd)
        # adding stdbuf if it's not there
        if "stdbuf" not in self.mtcmd:
            self.mtcmd = "stdbuf -oL "+self.mtcmd
        self.process = Popen(self.mtcmd, bufsize=0, stdin=PIPE, stdout=PIPE, shell=True) #, encoding="utf-8")

        # MT cache -- if a string was already translated, it's not sent to MT again
        self.mt_cache = {}  # TODO: make it LRU cache with maximum size. It may cause OOM.
        self.mt_cache[""] = ""

        if args.sourceOut:
            self.sourceOut = True
        else:
            self.sourceOut = False
        if args.timestampsOut:
            self.timestampsOut = True
        else:
            self.timestampsOut = False

        # a prefix of logfiles, or None
        self.mtlog = args.mtlog
        self.start_time = -1

        self.translate_batch_list = []
        self.batch_delimiter = args.batch_delimiter

        self.unsafe = args.unsafe


    def cached_translations(self, segments):
        ret = []
        for s in segments:
            if s.text in self.mt_cache:
                tr = self.mt_cache[s.text]
#                tr = "CACHES+%s %s" % (self.mt_cache[s.text], str(s.timestamps))
            else:
                tr = None
            ret.append(tr)
        return ret

    def _translate(self,msg):
        if not msg.strip():
            return ""
        msg += "\n"
        if self.mtlog:
            t = time.time() - self.start_time
            self.in_log.write("%f %s" % (t,msg))
            self.in_log.flush()
        msg = msg.encode(encoding="utf-8")
        self.process.stdin.write(msg)
        self.process.stdin.flush()
        tmsg = self.process.stdout.readline().decode(encoding="utf-8", errors="ignore")
        if self.mtlog:
            t = time.time() - self.start_time
            self.out_log.write("%f %s" % (t,tmsg))
            self.out_log.flush()
        return tmsg.strip()

    def translate(self, segments):
        cached = [self.mt_cache[s.text] if s.text in self.mt_cache else None for s in segments]
        to_translate = [s.text for c,s in zip(cached,segments) if c is None]
        batch = self.batch_delimiter.join(to_translate)
        trans_batch = self._translate(batch).split(self.batch_delimiter)
        trans_batch = [ t if t != "<EMPTY>" else "" for t in trans_batch ]
        for src, trg in zip(to_translate, trans_batch):
            self.mt_cache[src] = trg
        translations = []
        i = 0
        for c in cached:
            if c is None:
                if i>=len(trans_batch):
                    amsg = "Number of translated batches is lower than expected. index i=%d, len(trans_batch)=%d" % (i, len(trans_batch))
                    if self.unsafe:
                        tr = "INTERNAL BUG: " + amsg
                    else:
                        raise Exception(amsg)
                else:
                    tr = trans_batch[i]
                i += 1
            else:
                tr = c
            translations.append(tr)
        return translations

    def open_logs(self, start_time):
        self.start_time = start_time

        if self.mtlog is not None:
            # these files are not closed properly :(
            self.in_log = open(self.mtlog+".in.txt", "w")
            self.out_log = open(self.mtlog+".out.txt", "w")

class MTWrapper:
    def __init__(self, buff, translator, source_out=False, lang="en", eventsIn=False):
        self.buff = buff
        self.translator = translator

        self.stop_processing = False
        self.start_time = time.time()

        self.translator.open_logs(self.start_time)

        self.source_out = source_out
        self.lang = lang

        self.eventsIn = eventsIn

    def input_thread(self, in_stream):
        last_update_time = None
        try:
            #for line in yield_events(in_stream):
            if not self.eventsIn:
                in_stream = original_to_brief(yield_events(in_stream, timestamps=False, lang=self.lang))
            for line in in_stream:
                if self.stop_processing:
                    break
                t = time.time()
                tc = (-self.start_time + t)*1000
                self.buff.insert(line.strip(), curr_time=tc)
                with self.cv:
                    self.cv.notify()
#        except:
#            raise
        finally:
            self.stop_processing = True
            with self.cv:
                self.cv.notify()


    def yield_output(self, trans, segments):
        for t,s in zip(trans, segments):
            out = '%d %d %s' % (s.index, s.index+s.status, t)
            if self.source_out:
                out += '|||%s' % s.out_text()
            yield out

    def output(self, trans, segments):
        for out in self.yield_output(trans, segments):
            print(out)
        sys.stdout.flush()

    def output_cached(self, cached_trg, src_updates):
        ret = []
        is_beg = True
        for c, s in zip(cached_trg, src_updates):
            if c is not None and is_beg:
                #self.output(["(cached) "+c],[s])
                self.output([c],[s])
            else:
                is_beg = False
                ret.append(s)
        return ret

    def process_translations(self, src_updates):
        # if the updates start with already translated sentences,
        # differing only in status or timestamps
        cached_trg = self.translator.cached_translations(src_updates)

        # we output them immediately, without waiting for the
        # translation, and remove them from src_updates
        src_updates = self.output_cached(cached_trg, src_updates)

        # translate. If a cached sentence is in the middle of
        # src_updates, then it's returned together with previous,
        # without translating it for a second time
        trg = self.translator.translate(src_updates)

        self.output(trg, src_updates)

    def translating_thread(self):
        very_last = False  # the very last iteration. When stop_processing is set to True by input thread, 
        # there can be untranslated content, so one more iteration is needed.
        try:
            last_translate_time = -1
            while not self.stop_processing or not very_last:
                if self.stop_processing:
                    very_last = True
                t = time.time()
                tc = (-self.start_time + t)*1000

                if self.buff.last_insert_time is None: 
                    with self.cv:
                        self.cv.wait()
                    # buffer is empty at the beginning
                    continue
                if last_translate_time is not None and self.buff.last_insert_time <= last_translate_time:
                    if not very_last:  # don't wait if it is the last iteration. Input is over.
                        with self.cv:
                            self.cv.wait()
                    # no new content since last time
                    continue
                src_updates = self.buff.get_updates(last_translate_time)
                if not src_updates:
                    continue
                last_translate_time = max(tc,max(s.receive_time for s in src_updates))
                self.process_translations(src_updates)
        #except:
        #    raise
        finally:
            self.stop_processing = True

    def process(self, in_stream):
        self.stop_processing = False
        self.start_time = time.time()

        cv = threading.Condition()
        self.cv = cv
        translating_thread = threading.Thread(name="translating_thread",
            target=self.translating_thread)
        translating_thread.start()

        self.input_thread(in_stream)

        translating_thread.join()

class NonBatchingMTWrapper(MTWrapper):
    def process_translations(self, src_updates):
        for s in src_updates:
            trg = self.translator.translate([s])
            self.output(trg, [s])

parser = argparse.ArgumentParser(description=r"""MT Wrapper.""")

# it wouldn't be readable in help message :(
""" Expected input format:

9446 13036 I 'm going...
9446 13396 I 'm going to talk...
12736 13756 I 'm going to talk today.
12736 14116 I 'm going to talk today about...
12736 14246 I 'm going to talk today about...
12736 14936 I 'm going to talk today about in...

Internally it uses online-text-flow-events and outputs the brief events:

100 101 Já jdu...
100 110 Dnes budu mluvit o energetice a klimatu.
200 201 A to by mohlo...
200 201 A to by se mohlo zdát trochu...
200 201 A to by se mohlo zdát trochu překvapivé.
200 201 A to by se mohlo zdát trochu překvapivé...
200 201 A to by se mohlo zdát trochu překvapivé, protože...
200 201 A to by se mohlo zdát trochu překvapivé, protože Michael...
200 201 A to by se mohlo zdát trochu překvapivé, protože můj plný úvazek...
200 201 A to by se mohlo zdát trochu překvapivé, protože můj plný úvazek pracuje v...
"""

parser.add_argument('--mt', help='MT process command to run as a subprocess. If it does not start with "stdbuf -oL", mt-wrapper inserts it.', nargs="+", default=["cat"])
parser.add_argument('--mtlog', help='A prefix of logfiles for input and output of the MT process. .in.txt and .out.txt will be appended.',default=None,type=str)
#parser.add_argument('--memory', help='Translation memory files. Source and target.',default=[], type=str, nargs=2)
parser.add_argument('--min_status', help='Minimum sentence status to translate.', default=0, type=int)
parser.add_argument('--batch-delimiter', help='Batch delimiter for simple-batching-marian-server-server.py.',default="|||", type=str)
parser.add_argument('--no-batching', help='Disable MT batching. This should be used for those MT whose marian-server-server.py does not allow it.',dest="no_batching",action="store_true")
parser.add_argument('--unsafe', help='Ignore mismatched input and output batches of MT process. MT-wrapper does dot fail, and the outputs may be wrong. Should be used only in debugging.',dest="unsafe",action="store_true")
#parser.add_argument('--timestampsOut', help='Output real timestamps, in additional to the artificial ones (numbers of sentences).', dest="timestampsOut",action="store_true")
parser.set_defaults(timestampsOut=False,no_batching=False)
parser.add_argument('--sourceOut', help='Output |||-delimited target and source. Without this option, only the target.', dest="sourceOut",action="store_true")
parser.set_defaults(sourceOut=False)

parser.add_argument('--eventsIn', help='Input is from online-text-flow '
    'events -b , or from mt-wrapper. Artificial timestamps are expected instead '
    'of the real ones.', dest="eventsIn",action="store_true")
parser.set_defaults(eventsIn=False)

parser.add_argument('lang', help='Source language code for MosesSentenceSplitter. Default is en.', type=str, default="en", nargs="?")

#parser.set_defaults(finalizationFreeze=False)
#parser.add_argument('--finalization-freeze', help='If used, updates of sentences after --finalization-time will be ignored in context of adjacent sentences.', dest="sourceOut",action="store_true")
#parser.add_argument('--finalization-time', help='Miliseconds after ASR finalizes a sentence (status 100), after which the sentence will be finalized. ' +
#        'Updates will afect context of following sentences, but won\'t be presented to the user. Use --finalization-freeze to freeze it for context.', type=int, default=None)
#parser.add_argument('--freeze-time', help='TODO Milliseconds after ASR completes a sentence (status 10), after which all updates will be ignored. -1 for infinity.', type=int, default=10000)
parser.add_argument('--mask-k', help='Mask last K words of status 1 sentences for MT.', type=int, default=0, metavar="K")
#parser.add_argument('--mask-time', help='TODO Mask last T milliseconds of ASR updates (those with status 1) for MT.', type=int, default=0, metavar="T")


def main():
    args = parser.parse_args()
    translator = Translator(args.mt, args)
    buff = Buffer(args.mask_k, args.min_status)
    if args.no_batching:
        wr = NonBatchingMTWrapper
    else:
        wr = MTWrapper
    mtwrapper = wr(buff, translator, args.sourceOut, lang=args.lang, eventsIn=args.eventsIn)
    mtwrapper.process(sys.stdin)


if __name__ == "__main__":
    main()
