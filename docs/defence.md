# Interview defence sheet

37 questions I expect, grouped by topic. Answers are mine to write: the space under each is deliberately empty.

## Agent design

**1. Walk me through what happens, step by step, when you run `verity run VRT`.**

&nbsp;

&nbsp;

---

**2. Why three agents rather than one model call that researches, writes and checks?**

&nbsp;

&nbsp;

---

**3. Why is the Researcher on a cheap model and the Writer on a strong one? What would change if you swapped them?**

&nbsp;

&nbsp;

---

**4. How does the Writer know which number to cite, and what stops it from inventing a source id?**

&nbsp;

&nbsp;

---

**5. Why does the fact-checker re-fetch values with its own ledger instead of reading the Writer's sources?**

&nbsp;

&nbsp;

---

**6. Why cap revision at two rounds? What happens to an error that survives both?**

&nbsp;

&nbsp;

---

## Why no framework

**7. Why did you write the agent loop yourself instead of using LangChain or CrewAI?**

&nbsp;

&nbsp;

---

**8. What would you lose, and what would you gain, by moving this to a framework or to a managed agent platform?**

&nbsp;

&nbsp;

---

**9. How would you add a new tool, and what has to change for the model to use it?**

&nbsp;

&nbsp;

---

## XBRL and data quirks

**10. Eaton has no operating-income line. How did you get its EBIT, and how do you know it is right?**

&nbsp;

&nbsp;

---

**11. What is the difference between a duration fact and an instant fact, and where did that matter?**

&nbsp;

&nbsp;

---

**12. How do you handle fiscal years that don't end in December? Give an example from your universe.**

&nbsp;

&nbsp;

---

**13. A company restates last year. Which number does your system use, and could that mark a correct claim as wrong?**

&nbsp;

&nbsp;

---

**14. How did you deal with Powell's 3-for-1 split, and why did you not change the reported EPS?**

&nbsp;

&nbsp;

---

**15. Why did 11% of values need a fallback, and what is the risk of falling back by year?**

&nbsp;

&nbsp;

---

**16. Why not use a data vendor or the SEC frames API instead of building a concept map?**

&nbsp;

&nbsp;

---

## Evaluation design

**17. How did you choose the seven error types? Which real-world error is missing from the list?**

&nbsp;

&nbsp;

---

**18. Your recall is 98.2%. Why should I not believe that number for a real LLM-written note?**

&nbsp;

&nbsp;

---

**19. How did you make sure an injected error was actually an error? What bug did you find in your own injector?**

&nbsp;

&nbsp;

---

**20. What is the difference between 'caught' and 'fixed', and why is the residual rate higher than the miss rate?**

&nbsp;

&nbsp;

---

**21. How would you measure false alarms on LLM prose, where the checker might misread a number?**

&nbsp;

&nbsp;

---

**22. What would the baseline-vs-agent experiment show, and how would you type the failures?**

&nbsp;

&nbsp;

---

**23. How would you build a held-out test set so you don't tune the checker to your own injector?**

&nbsp;

&nbsp;

---

## Failure modes

**24. Show me an error your fact-checker misses, and explain why it misses it.**

&nbsp;

&nbsp;

---

**25. A fabricated sentence cited a real source. How did your first revision loop make it worse, and how did you fix it?**

&nbsp;

&nbsp;

---

**26. What happens if a 10-K contains text that tries to instruct the model (prompt injection)?**

&nbsp;

&nbsp;

---

**27. How are qualitative claims (strategy, risks) checked, and where does that break down?**

&nbsp;

&nbsp;

---

**28. What happens if the Writer outputs a number in words ("ten billion") or a range?**

&nbsp;

&nbsp;

---

## Cost and operations

**29. What does a note cost in rules mode and in LLM mode, and what dominates the LLM cost?**

&nbsp;

&nbsp;

---

**30. How does replay mode work, and why does the cache key include the model and effort level?**

&nbsp;

&nbsp;

---

**31. How would you cut cost by 10x without losing accuracy?**

&nbsp;

&nbsp;

---

**32. What would you monitor in production, and what would page someone?**

&nbsp;

&nbsp;

---

## How this would work at a fund or bank

**33. Who signs off a note before it reaches a client, and what does the fact-check log give them?**

&nbsp;

&nbsp;

---

**34. How does this map to MAS's FEAT principles and the AI Risk Management Guidelines?**

&nbsp;

&nbsp;

---

**35. How would you rate Verity's risk materiality on Impact, Complexity and Reliance?**

&nbsp;

&nbsp;

---

**36. How would you extend this to non-US companies like Delta Electronics?**

&nbsp;

&nbsp;

---

**37. What would make you trust this enough to let it publish without a human?**

&nbsp;

&nbsp;

---
