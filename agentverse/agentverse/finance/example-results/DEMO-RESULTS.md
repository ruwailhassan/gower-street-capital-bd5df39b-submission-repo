# Finance playground results

All cases are synthetic practice data. No real money, live prices or account access.

## 1. Follow the money

Checked 7 transactions. Found 1 three-account transfer cycle: **T03, T04, T05**.
A cycle is a reason to investigate context, not proof of fraud. Large transfers alone are not enough to establish wrongdoing.

**Your challenge:** build an investigator that explains the evidence and avoids treating ordinary salary, rent and supplier payments as proven fraud.

## 2. A positive balance can hide a cash crunch

Both salary cases finish with **£1,600.00**. The delayed-salary case has a temporary shortfall of **£400.00**.
The balance first turns negative on **2026-11-03**.

| Date | Event | Change | Balance after event |
| --- | --- | --- | --- |
| 2026-11-02 | rent | -£900.00 | £100.00 |
| 2026-11-03 | bills | -£200.00 | -£100.00 |
| 2026-11-04 | food | -£300.00 | -£400.00 |
| 2026-11-10 | salary | £2,000.00 | £1,600.00 |

**Your challenge:** explain when the money runs out and compare changed payment timing, without inventing income or making account changes.

## 3. Paper profits after costs

Start: **£1,000.00**. Same rising price series, three explicit assumptions:

- No fees: **£1,500.00** final cash.
- Fixed trading fees: **£1,493.00** final cash.
- Fees plus 10 basis points of adverse slippage: **£1,490.03** final cash.

Differences include position size and rounding, not just fees. This is a buy-and-hold accounting baseline, not evidence of a profitable strategy.

**Your challenge:** test your own strategy on held-out data, include costs, compare with cash and buy-and-hold, and show it cannot use future prices.

## Next

Pick one challenge. Ask Antigravity to use finance-build to make one improvement, then finance-test to check it independently.
The raw calculated evidence is in results.json. These visible practice cases are not a hidden competition benchmark.
