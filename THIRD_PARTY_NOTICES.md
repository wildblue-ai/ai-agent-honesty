# Third-party notices

This repository includes material from the third-party project below. Its license is reproduced as required.

## anthropic-experimental/agentic-misalignment

- **Source:** https://github.com/anthropic-experimental/agentic-misalignment, commit `ea0630e1a3eaae7f9f9740fd2703229d3854ccda`
- **What is included:** one paragraph, the `SCRATCHPAD_REASONING_FORMAT` string from `templates/system_prompt_templates.py`, reproduced verbatim in `prompts/scratchpad_v1.md`. The surrounding blank lines were stripped.
- **License:** MIT

```
MIT License

Copyright (c) 2025 Aengus Lynch

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

## safety-research/impossiblebench

- **Source:** https://github.com/safety-research/impossiblebench, commit `d4f9a149db2b9cec0fed7bab01d91c07ee10aca2`
- **What is included:** an adapted sentence, from the human-intervention instruction prompt in `demo.py`, in
  `prompts/hatch_notice_v1.md`, and the tool name `flag_for_human_intervention`. Only the task nouns were changed
  (tests/function → task/partners' calendars; "submit with the string" → "call"). No code is included.
- **License:** MIT

```
MIT License

Copyright (c) 2025 ImpossibleBench Team

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

## Not included

No ImpossibleBench code is included. That work is cited in `credits.md` as the source of the impossible-task idea
and of the step 3 escape-hatch wording. Python packages are installed from PyPI, not
redistributed; see `requirements.lock`.
