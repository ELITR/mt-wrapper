# MT Wrapper

MT Wrapper is a tool that receives punctuated re-translating (or incremental) ASR
input, segments it by punctuation to sentences, and translates them trough
machine translation subprocess.

It was created by Dominik Macháček within the ELITR project. It was
first used and described in [ELITR submission at IWSLT
2020](https://aclanthology.org/2020.iwslt-1.25/). Since that, it
is a part of the ELITR framework for complex and distributed system for live
speech translation.


MT Wrapper has two threads: 

- receiving thread receives ASR input and updates a buffer, so that it stores
  only the currently valid, latest hypotheses

- translating thread gets a batch of sentences from the buffer, consults the
  buffer and either translates and caches them, or it retrieves them from
  the cache immediately and output them.

In practice, translation is usually not instant, it takes around 300 ms (for
a usual Marian MT model), so the preliminary ASR hypotheses which were rewritten during the
translation are skipped. If the MT translates one batch in 300 ms, then in
average it lags 300 ms behind ASR, and this lagging is constant. 
The minimum lag is around zero, for very short or cached sentences. The
maximum can be around 1 second (sum of 2 subsequent batch translations, if
they take 500 ms).


## Usage

MT Wrapper input is the punctuated text from ASR:

```
9446 13036 I 'm going...
9446 13396 I 'm going to talk...
12736 13756 I 'm going to talk today.
12736 14116 I 'm going to talk today about...
```

### Basic example usage

Assume there is MTCMD -- a commandline tool that transfers one text input line
into one text output line, after some delay. For testing and debugging, you
can define

```
MTCMD='tr a-z A-Z'
```

Otherwise, it can be e.g. a script that sends the text through any MT
service.

```
stdbuf -oL ./replay-ts.py 19000 < examples/ted_767.wav.seg.txt | ./mtwrapper.py --mt "$MTCMD" 2>/dev/null
```

### Advanced usage

- inside is MosesSentenceSplitter for splitting sentences by language-specific
  rules. By default it's set for English. For other language on source, you
  must use `lang` positional parameter, e.g. `./mtwrapper.py cs --mt ...`.

- `--sourceOut` is intended only for debugging

- `--min_status` and `--mask-k` parameters control the stability and latency

	- `--min_status` is by default 1 = incoming. Other values are 10 = expected
  and 100 = completed.

Options:

```
(p3) d@y:~/Plocha/elitr/cruise-control/mt-wrapper$ ./mtwrapper.py -h
usage: mtwrapper.py [-h] [--mt MT [MT ...]] [--mtlog MTLOG]
                     [--min_status MIN_STATUS]
                     [--batch-delimiter BATCH_DELIMITER] [--no-batching]
                     [--sourceOut] [--eventsIn] [--mask-k K]
                     [lang]

MT Wrapper.

positional arguments:
  lang                  Source language code for MosesSentenceSplitter.
                        Default is en.

optional arguments:
  -h, --help            show this help message and exit
  --mt MT [MT ...]      MT process command to run as a subprocess. If it does
                        not start with "stdbuf -oL", mt-wrapper inserts it.
  --mtlog MTLOG         A prefix of logfiles for input and output of the MT
                        process. .in.txt and .out.txt will be appended.
  --min_status MIN_STATUS
                        Minimum sentence status to translate.
  --batch-delimiter BATCH_DELIMITER
                        Batch delimiter for simple-batching-marian-server-
                        server.py.
  --no-batching         Disable MT batching. This should be used for those MT
                        whose marian-server-server.py does not allow it.
  --sourceOut           Output |||-delimited target and source. Without this
                        option, only the target.
  --eventsIn            Input is from online-text-flow events -b , or from mt-
                        wrapper. Artificial timestamps are expected instead of
                        the real ones.
  --mask-k K            Mask last K words of status 1 sentences for MT.
```


### Batching in the MT command:

By default, the MT Wrapper assumes that the MT command supports batching, it
means translating multiple segments individually, but at the same time.
If `--no-batching` option is not used, the MT Wrapper collects all the
sentences that were updated from the last iteration, pastes them with |||
and sends in one message throught the MT command. Internally, the MT command
cuts them, translates them in one batch, pastes them by ||| and sends back
in one message. Finally, MT wrapper cuts them again.

### Multi-target MT

MT wrapper works for multi-target MT the same way as for the single target.
In ELITR framework, there is "rainbow" protocol of the multi-tartet MT
messages. The format is like: 

```
de TAB German translation sentence 1 TAB ... xy TAB xy translation  sentence
1 |||de TAB German translation sentence 2 TAB ... xy TAB xy translation
sentence 2|||...
```

MT Wrapper doesn't care about the format. Then, other tools in ELITR are
used to handle the target languages.

## Installation


The only dependency is the ELITR `online-text-flow`: https://github.com/ELITR/online-text-flow/

## How to cite

Please, refer to Section 5.3 in
https://aclanthology.org/2020.iwslt-1.25.pdf, and cite:

```
@inproceedings{machacek-etal-2020-elitr,
    title = "{ELITR} Non-Native Speech Translation at {IWSLT} 2020",
    author = "Mach{\'a}{\v{c}}ek, Dominik  and
      Kratochv{\'\i}l, Jon{\'a}{\v{s}}  and
      Sagar, Sangeet  and
      {\v{Z}}ilinec, Mat{\'u}{\v{s}}  and
      Bojar, Ond{\v{r}}ej  and
      Nguyen, Thai-Son  and
      Schneider, Felix  and
      Williams, Philip  and
      Yao, Yuekun",
    editor = {Federico, Marcello  and
      Waibel, Alex  and
      Knight, Kevin  and
      Nakamura, Satoshi  and
      Ney, Hermann  and
      Niehues, Jan  and
      St{\"u}ker, Sebastian  and
      Wu, Dekai  and
      Mariani, Joseph  and
      Yvon, Francois},
    booktitle = "Proceedings of the 17th International Conference on Spoken Language Translation",
    month = jul,
    year = "2020",
    address = "Online",
    publisher = "Association for Computational Linguistics",
    url = "https://aclanthology.org/2020.iwslt-1.25",
    doi = "10.18653/v1/2020.iwslt-1.25",
    pages = "200--208",
    abstract = "This paper is an ELITR system submission for the non-native speech translation task at IWSLT 2020. We describe systems for offline ASR, real-time ASR, and our cascaded approach to offline SLT and real-time SLT. We select our primary candidates from a pool of pre-existing systems, develop a new end-to-end general ASR system, and a hybrid ASR trained on non-native speech. The provided small validation set prevents us from carrying out a complex validation, but we submit all the unselected candidates for contrastive evaluation on the test set.",
}
```


