# Stage 1 per-query measurements

Scores are probabilities. Peak columns are PyTorch allocated/reserved MiB. Positive seconds use p ≥ 0.50, a diagnostic starting threshold, not a validated acceptance rule.

## wick-driving, context 8,192

source 04:00.000–06:00.000; 2 fps; model image 352×128; 5,280 video tokens. Preprocess 1.235 s; encode 0.983 s; features retained only in RAM: 25.78 MiB. Image-preprocessing budget 8,192; longest padded question 7,552 tokens within language context 8,192.

| Query | Max | Mean | p95 | Seconds ≥ .50 | Query s | Peak allocated / reserved MiB |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| A car is visible. | 0.9825 | 0.6378 | 0.9801 | 77.75 | 0.910 | 10170.1 / 10464.0 |
| People are fighting. | 0.8852 | 0.4631 | 0.8667 | 58.75 | 0.907 | 10170.0 / 10464.0 |
| John Wick drives a car | 0.9867 | 0.3842 | 0.9759 | 51.00 | 0.875 | 10170.1 / 10464.0 |
| a man in a black suit drives a car | 0.9841 | 0.3977 | 0.9707 | 52.00 | 0.880 | 10173.5 / 10464.0 |
| A giraffe walks across a field. | 0.0258 | 0.0009 | 0.0014 | 0.00 | 0.879 | 10172.4 / 10464.0 |

Contact sheet: `D:\SpearFia\library\jev\stage1-2026-10-30\wick-driving-8192.jpg`.

## wick-driving, context 16,384

source 04:00.000–06:00.000; 2 fps; model image 512×192; 11,520 video tokens. Preprocess 1.529 s; encode 0.673 s; features retained only in RAM: 56.25 MiB. Image-preprocessing budget 16,384; longest padded question 13,760 tokens within language context 16,384.

| Query | Max | Mean | p95 | Seconds ≥ .50 | Query s | Peak allocated / reserved MiB |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| A car is visible. | 0.9830 | 0.6097 | 0.9814 | 70.75 | 1.633 | 11012.9 / 11572.0 |
| People are fighting. | 0.9586 | 0.2433 | 0.8582 | 20.75 | 1.614 | 11012.8 / 11572.0 |
| John Wick drives a car | 0.9902 | 0.3794 | 0.9833 | 51.00 | 1.653 | 11012.9 / 11572.0 |
| a man in a black suit drives a car | 0.9883 | 0.3656 | 0.9809 | 51.00 | 1.649 | 11013.1 / 11572.0 |
| A giraffe walks across a field. | 0.0051 | 0.0006 | 0.0014 | 0.00 | 1.603 | 11013.0 / 11572.0 |

Contact sheet: `D:\SpearFia\library\jev\stage1-2026-10-30\wick-driving-16384.jpg`.

## wick-driving, context 32,768

source 04:00.000–06:00.000; 2 fps; model image 736×288; 24,840 video tokens. Preprocess 1.954 s; encode 1.535 s; features retained only in RAM: 121.29 MiB. Image-preprocessing budget 32,768; longest padded question 27,072 tokens within language context 32,768.

| Query | Max | Mean | p95 | Seconds ≥ .50 | Query s | Peak allocated / reserved MiB |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| A car is visible. | 0.9821 | 0.6226 | 0.9774 | 70.75 | 3.353 | 12793.1 / 13756.0 |
| People are fighting. | 0.9700 | 0.2369 | 0.9200 | 16.75 | 3.376 | 12793.1 / 13756.0 |
| John Wick drives a car | 0.9900 | 0.3612 | 0.9849 | 49.00 | 3.350 | 12793.1 / 13756.0 |
| a man in a black suit drives a car | 0.9853 | 0.3606 | 0.9775 | 49.00 | 3.428 | 12793.3 / 13756.0 |
| A giraffe walks across a field. | 0.0036 | 0.0004 | 0.0010 | 0.00 | 3.375 | 12793.3 / 13756.0 |

Contact sheet: `D:\SpearFia\library\jev\stage1-2026-10-30\wick-driving-32768.jpg`.

## wick-fight, context 8,192

source 03:00.000–05:00.000; 2 fps; model image 288×160; 5,400 video tokens. Preprocess 2.503 s; encode 0.399 s; features retained only in RAM: 26.37 MiB. Image-preprocessing budget 7,340; longest padded question 7,616 tokens within language context 8,192.

| Query | Max | Mean | p95 | Seconds ≥ .50 | Query s | Peak allocated / reserved MiB |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| A car is visible. | 0.9195 | 0.0806 | 0.7612 | 8.00 | 0.891 | 10191.6 / 10520.0 |
| People are fighting. | 0.9815 | 0.2090 | 0.9304 | 20.75 | 0.928 | 10191.6 / 10520.0 |
| John Wick drives a car | 0.7812 | 0.1285 | 0.5798 | 9.00 | 0.893 | 10191.6 / 10520.0 |
| a man in a black suit drives a car | 0.5684 | 0.0811 | 0.3673 | 2.00 | 0.894 | 10191.8 / 10520.0 |
| A giraffe walks across a field. | 0.0669 | 0.0119 | 0.0428 | 0.00 | 1.019 | 10191.7 / 10520.0 |

Contact sheet: `D:\SpearFia\library\jev\stage1-2026-10-30\wick-fight-8192.jpg`.

## wick-fight, context 16,384

source 03:00.000–05:00.000; 2 fps; model image 448×224; 11,760 video tokens. Preprocess 1.534 s; encode 0.698 s; features retained only in RAM: 57.42 MiB. Image-preprocessing budget 16,384; longest padded question 14,016 tokens within language context 16,384.

| Query | Max | Mean | p95 | Seconds ≥ .50 | Query s | Peak allocated / reserved MiB |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| A car is visible. | 0.9252 | 0.0558 | 0.2165 | 4.00 | 1.723 | 11043.8 / 11580.0 |
| People are fighting. | 0.9835 | 0.2776 | 0.9443 | 33.75 | 1.657 | 11043.8 / 11580.0 |
| John Wick drives a car | 0.7398 | 0.1742 | 0.4892 | 6.00 | 1.687 | 11043.8 / 11580.0 |
| a man in a black suit drives a car | 0.4907 | 0.1157 | 0.3838 | 0.00 | 1.674 | 11043.9 / 11580.0 |
| A giraffe walks across a field. | 0.1203 | 0.0202 | 0.0637 | 0.00 | 1.668 | 11043.9 / 11580.0 |

Contact sheet: `D:\SpearFia\library\jev\stage1-2026-10-30\wick-fight-16384.jpg`.

## wick-fight, context 32,768

source 03:00.000–05:00.000; 2 fps; model image 608×352; 25,080 video tokens. Preprocess 2.407 s; encode 1.959 s; features retained only in RAM: 122.46 MiB. Image-preprocessing budget 32,768; longest padded question 27,328 tokens within language context 32,768.

| Query | Max | Mean | p95 | Seconds ≥ .50 | Query s | Peak allocated / reserved MiB |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| A car is visible. | 0.2095 | 0.0384 | 0.1196 | 0.00 | 3.414 | 12827.0 / 13794.0 |
| People are fighting. | 0.9857 | 0.1925 | 0.9189 | 15.75 | 3.385 | 12827.0 / 13794.0 |
| John Wick drives a car | 0.0848 | 0.0231 | 0.0529 | 0.00 | 3.385 | 12827.0 / 13794.0 |
| a man in a black suit drives a car | 0.0800 | 0.0337 | 0.0692 | 0.00 | 3.383 | 12827.2 / 13794.0 |
| A giraffe walks across a field. | 0.0088 | 0.0019 | 0.0058 | 0.00 | 3.462 | 12827.1 / 13794.0 |

Contact sheet: `D:\SpearFia\library\jev\stage1-2026-10-30\wick-fight-32768.jpg`.

## long-gameplay, context 8,192

source 10:00.000–40:00.000; 0.2 fps; model image 224×96; 3,780 video tokens. Preprocess 3.420 s; encode 0.420 s; features retained only in RAM: 18.46 MiB. Image-preprocessing budget 5,440; longest padded question 7,552 tokens within language context 8,192.

| Query | Max | Mean | p95 | Seconds ≥ .50 | Query s | Peak allocated / reserved MiB |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| A car is visible. | 0.0744 | 0.0067 | 0.0203 | 0.00 | 0.914 | 10170.4 / 10500.0 |
| People are fighting. | 0.8971 | 0.1606 | 0.8712 | 280.00 | 0.937 | 10170.3 / 10500.0 |
| John Wick drives a car | 0.1478 | 0.0074 | 0.0268 | 0.00 | 0.933 | 10170.4 / 10500.0 |
| a man in a black suit drives a car | 0.7971 | 0.0209 | 0.0437 | 37.50 | 0.984 | 10170.7 / 10500.0 |
| A giraffe walks across a field. | 0.2913 | 0.0092 | 0.0272 | 0.00 | 0.972 | 10170.6 / 10500.0 |

Contact sheet: `D:\SpearFia\library\jev\stage1-2026-10-30\long-gameplay-8192.jpg`.

## long-gameplay, context 16,384

source 10:00.000–40:00.000; 0.2 fps; model image 352×192; 11,880 video tokens. Preprocess 4.161 s; encode 0.740 s; features retained only in RAM: 58.01 MiB. Image-preprocessing budget 15,640; longest padded question 15,680 tokens within language context 16,384.

| Query | Max | Mean | p95 | Seconds ≥ .50 | Query s | Peak allocated / reserved MiB |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| A car is visible. | 0.0296 | 0.0013 | 0.0048 | 0.00 | 1.937 | 11255.7 / 11860.0 |
| People are fighting. | 0.9657 | 0.1366 | 0.9582 | 240.00 | 1.935 | 11255.6 / 11860.0 |
| John Wick drives a car | 0.5963 | 0.0041 | 0.0018 | 7.50 | 1.869 | 11255.7 / 11860.0 |
| a man in a black suit drives a car | 0.7247 | 0.0052 | 0.0022 | 7.50 | 1.927 | 11256.1 / 11860.0 |
| A giraffe walks across a field. | 0.0316 | 0.0020 | 0.0077 | 0.00 | 1.970 | 11256.0 / 11860.0 |

Contact sheet: `D:\SpearFia\library\jev\stage1-2026-10-30\long-gameplay-16384.jpg`.

## long-gameplay, context 32,768

source 10:00.000–40:00.000; 0.2 fps; model image 512×288; 25,920 video tokens. Preprocess 3.068 s; encode 1.700 s; features retained only in RAM: 126.56 MiB. Image-preprocessing budget 32,768; longest padded question 29,696 tokens within language context 32,768.

| Query | Max | Mean | p95 | Seconds ≥ .50 | Query s | Peak allocated / reserved MiB |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| A car is visible. | 0.0200 | 0.0008 | 0.0025 | 0.00 | 3.866 | 13132.8 / 14174.0 |
| People are fighting. | 0.9441 | 0.1471 | 0.9324 | 220.00 | 3.848 | 13132.7 / 14174.0 |
| John Wick drives a car | 0.0076 | 0.0009 | 0.0032 | 0.00 | 3.794 | 13132.8 / 14174.0 |
| a man in a black suit drives a car | 0.5752 | 0.0050 | 0.0030 | 10.00 | 3.759 | 13133.0 / 14174.0 |
| A giraffe walks across a field. | 0.0447 | 0.0008 | 0.0019 | 0.00 | 3.782 | 13132.9 / 14174.0 |

Contact sheet: `D:\SpearFia\library\jev\stage1-2026-10-30\long-gameplay-32768.jpg`.
