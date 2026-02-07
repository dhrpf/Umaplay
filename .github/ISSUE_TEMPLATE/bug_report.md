---
name: Bug report
about: Create a report to help us improve
title: ''
labels: ''
assignees: ''

---

### **Version Information**

* **App Version:** `0.x.x`
* **Commit Hash:** `abc1234`
  *(You can verify this via `git status`.)*

---

## **Environment Setup**

### **Execution Environment**

Please indicate which environment you used:

* **Steam / SCRCPY / BlueStacks / Other**
* **ADB Connection:** (e.g. USB)
* **Device:** (e.g. Google Pixel 2 XL)
* **SCRCPY Command Used:**
Example:
  ```bash
  scrcpy --max-fps 10 -b 2M --video-codec=h264 --no-audio
  ```

### **Inference Backend**

* **YOLO/OCR API:** (e.g. Running separately on Linux, or directly)
* **Python Version:** 3.10
* **CUDA:** 13.0 Update 2
* **Server Command:**
Example if using remote:
  ```bash
  uvicorn server.main_inference:app --reload --host 0.0.0.0 --port 8001
  ```

### **Additional Environment**

* **Windows 11 VM:** Python 3.12

---

## **Trainee Configuration**

*(Exported from the trainee’s profile on the web platform)*

```json
{
  
}
```

---

## **Debug Logs**

Attach logs from `debug` folder. Log looks like 'debug_202X-XY-ZW_AB-CC.log'. With your real date time

> 📎 *Please upload or paste relevant log files here.*

---

## **Problem Description**

Describe the issue clearly:

* What went wrong?
* What behavior did you expect?
* How often does it occur?
* Any visual indicators, crashes, or unexpected actions?

---

## **Steps to Reproduce**

Provide all steps necessary to replicate the issue:

1. …
2. …
3. …
