# multifamily_scorecard
This project is an example place to work out the model development process for my team at work. The data used and the the goal is relevant to my job, which is an added benefit. I want to do the work (mostly) in Python to force myself to learn more (I'm more of an R user). I will constantly refer to the Federal Reserve's _Supervisory Guidance on Model Risk Management_, which is known as [SR 11-7](https://www.federalreserve.gov/supervisionreg/srletters/sr1107a1.pdf). This document contains the principles and standards to which model development and related activities at commercial banks are held.

## Purpose

SR 11-7 states that "[a]n effective model development process begins with a clear statement of purpose to ensure that model development is aligned with the intended use." (p. 5) The model, or models, that I'll develop here will not be used for anything other than exploring the model development process and producing examples of the issues that arise in real world development. However, we will imagine that a bank could use this model for a so-called rating scorecard. Banks use rating scorecards to assign to commercial borrowers a rating that indicates a certain level of default risk.

A bank uses these ratings in many of its activities: monitoring the overall risk of a particular portfolio, setting the levels of loan loss reserves, allocating capital, or charging business lines for the risk they take by making loans. In theory, these ratings put commercial loans on a scale that makes them comparable despite the various circumstances of each loan or borrower (e.g., what industry they operate in or, for real estate, what type of property it is and the existing or prospective tenants). Examples of such ratings are short and long-term bond ratings assigned by the "major" rating agencies, Moody's, S&P, and Fitch.

Each rating represents an interval of probabilities of default (PD). These probabilities usually are for a one-year time horizon and are said to be "through the cycle." That is, they represent the probability that the borrower will default within one year (from the date either of the assignment of the rating or the date of the inputs to the model) _regardless of the economic conditions that prevail during that year._ Regardless of this condition, the rating system includes a set number of categories, the ratings, and an interval of PDs. Each bank derives its own system of rating labels and probabilities, but there are some commonalities. First, there are usually between 10 and 15 ratings. Second, the worst four of these ratings are identified with regulatory categories. There are four categories: Special Mention, Substandard, Doubtful, and Loss (see, for example, the [Comptroller's Hanbook: Rating Credit Risk](https://www.occ.treas.gov/publications-and-resources/publications/comptrollers-handbook/files/rating-credit-risk/index-rating-credit-risk.html)). These categories represent the highest potential for default, where borrowers assigned the Loss (or even Doubtful) rating are, in fact, in default. The remaining better categories are all considered "Pass."

For our purposes, we will come up with our own rating scale. This will be somewhat arbitrary (this is _not_ the scale used by the bank I work for!). We'll use 10 ratings. While the rating agencies use letters (AAA, AA, A, BBB, etc.), many banks label their ratings with numerals. While simple (a numeral with a larger numerical value is riskier than one with a smaller numerical value), it commonly leads to the nonsensical use of the rating labels _as numbers_. For example, banks will "calculate" the weighted average rating as $\sum_i R_iC_i$ where $R_i$ is the rating of borrower $i$ and $C_i$ is borrower $i$'s proportion of committed exposure in the portfolio. 

TODO: Rating scale

## Design, theory, and logic
SR 11-7 outlines several principles related to the design of models.

- It should be "well documented." (p. 6)
- It should be "generally supported by published research and sound industry practice." (p. 6)
- The "methodologies and processing components that implement the theory, including the mathematical specifications and the numerical techiniques and approximations, should be explained in detail with particular attention to merits and limitations." (p. 6)
- "Developers should ensure that the components work as intended, are appropriate for the intended business purpose, and are conceptually sound and mathematically and statistically correct." (p. 6)
- Developers should compare their chosen theory or approach to alternatives.

TODO: Possible theories and methods

## Data
The data we will use is freely available from [Fannie Mae](https://capitalmarkets.fanniemae.com/credit-risk-transfer/multifamily-credit-risk-transfer/multifamily-loan-performance-data). It contains details of performance information and attributes of multifamily (aka, apartment) loans it has acquired since January 1, 2000. Over 67,000 loans are in the dataset representing overr 88% of FNMA's multifamily acquisitions during that period. This dataset is quite large, in some cases much larger than what a typical regional or smaller commercial bank would have internally.

According to lore, a data scientist spends 80% of his time on collecting, cleaning, and manipulating data. My personal experience accords with this statement, though it can be more or less true depending on the circumstance. In any case, some issues that I've run into with respect to dealing with datasets are:

- cleaning data, especially dealing with missing values, inconsistent reliability of observations through time;
- keeping track of different versions of cleaned/transformed datasets;
- transitioning from exploratory analyses to "data pipelines;"
- maintaing appropriate documentation of data processing for development and production over time;
- periodically updating the dataset as more observations are collected while maintaining reproducibility of models and other artifacts from specific versions of the dataset;
- converting data specifications used in model development to those required for executing the model in production, especially when development datasets are built from a variety of sources that do not have the same schema as the source used in production;
- verifying the "completeness and accuracy" (a favorite phrase of auditors) of the data; and,
- choosing (if there is such an option!) the right tools for storage, querying, and maintaining data.

While SR 11-7 does not detail all of these elements in its discussion of data, its principles cover all of these issues.

- There should be a "rigorous assessment of data quality and relevance." (p. 6)
- "Developers should demonstrate that such data and information are suitable for the model and that they are _consistent with the theory behind the approach and with the chosen methodology_." (p. 6, emphasis added)
- "[I]f assumptions are made to adjust the data and information, these factors should be properly tracked and analyzed so that users are aware of the potential limitations." (p. 6)
- There should be "appropriate documentation." (p. 6)

The guidance also discusses the use of proxies or external (to the bank) data. For example, the loans in the FNMA dataset may have been originated by a bank, but FNMA has specific requirements about the characteristics of loans that it acquires. Furthermore, these loans are securitized, which creates some distance between the borrower and the owner of the loan. A consequence of this fact is that securitized loans are perceived to perform worse than their bank counterparts. There are likely many reasons for this perception, but one of them is that a bank, when faced with a borrower experiencing financial difficulties, has an incentive (in many cases, at least) to work with the client to make sure the loan is repaid. This relationship between bank and client has value to both parties, but it is something that is less true for a securitized loan. All of this is to say that if we were to develop a model on FNMA data but _apply it to a particular bank's loans_ we need to account for this difference (among others). Thus, SR 11-7 "[i]f data and information are not representative of the bank's portfolio...these factors hsould be properly tracked and analyzed so that users are aware of potential limitations. This is particularly important for external data and information."

External data are not the only proxies that might be used. 
## Testing

## Implementation

## Documentation

