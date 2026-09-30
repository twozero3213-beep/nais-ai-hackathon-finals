rm(list=ls())
dev.off()

library(tidyverse)
library(psych)
library(parameters)
library(robustbase)
library(DescTools)
library(metafor)
library(wec) # For weighted effect coding of Education

### Function for checking exclusions
get_exclusions <- function(d, dataset) { ### Inclusion/Exclusion criteria
  
  print(nrow(d))  ### Number of rows in data frame. Several of these have few responses (e.g., people started the survey and then stopped).
  
  print("Remove cases where people did not complete all questions")
  d <- d[complete.cases(d),]  # Now exclude other forms of missing response
  print(nrow(d))
  
  print("Remove cases where people had selected something other than 1 rung on the SSS ladder")
  d <- d %>%    # So, first deal with SSS ladder
    select(matches("SSS")) %>% 
    reduce(`+`) %>%
    mutate(d, N_SSS = .)
  d <- subset(d, d$N_SSS==1)
  print(nrow(d))
  
  print("Exclude duplicates")
  d <- subset(d, d$duplicate==0)  
  print(nrow(d))
  
  if ((dataset=="UK")|(dataset=="US2")) {  # These checks are only for the UK and second US sample
    print("Remove self-reported past participation")
    d <- subset(d, d$pastatt==1)
    print(nrow(d))
  }
  if (dataset=="UK") {
    print("Remove people who might not be from the UK")
    d <- subset(d, d$country_name=="United Kingdom")
    print(nrow(d))
  }
  
  print("Remove people under 18 and over 100")
  d <- subset(d, (d$age>=18 & d$age<=100))
  print(nrow(d))
  
  print("Remove people who fail attention check")
  d <- subset(d, d$ENV_5==2)
  print(nrow(d))
  
  return(d)
}

set_incabs <- function(d) { ### Function for setting income -- pass in current data frame 
  
  # Use Pareto formula to estimate mid-point for top category
  # See e.g., Parker & Fenwick (1983).
  a <- data.frame(table(d$income))  # Checker whether some bins are empty
  ftop <- a$Freq[a$Var1==16]   # Could be problems if top or second-to-top bin are empty
  ftopmin1 <- a$Freq[a$Var1==15]
  Ltop <- 150
  Ltopmin1 <- 140.001
  V <- (log(ftopmin1+ftop)-log(ftop))/(log(Ltop) - log(Ltopmin1))
  Mtop <- Ltop*(2^(1/V))  # Pareto-curve  median
  d$incabs <- 5 + (d$income-1)*10
  d$incabs[d$income==16] <- Mtop
  
  return(d)
  
}

# Function for getting SSS, PRD, ENV, and z-scoring etc
make_vars <- function(d, dataset) {
  
  # SSS
  d$SSS <- d %>%
    select(starts_with("SSS")) %>%
    max.col
  ####
  
  # PRD -- reverse-score questions 2 and 4
  d$PRD_2 <- 7-d$PRD_2
  d$PRD_4 <- 7-d$PRD_4
  
  if (dataset=="UK") { # omega calculation produces warning
    PRD_reliability <- d %>% select(starts_with("PRD")) %>%  omega
    print(paste("PRD omega_h = ", PRD_reliability$omega_h))
  } 
  PRD_alpha <- d %>% select(starts_with("PRD")) %>% alpha
  print(paste("PRD alpha = ", PRD_alpha$total$raw_alpha))
  
  d <- d %>%
    mutate(PRD_Mean = select(., starts_with("PRD_")) %>%
             rowMeans(na.rm = TRUE))
  ####
  
  # ENV
  d <- subset(d, select=-ENV_5) # Drop the attention check question
  # Now replace "not applicable" with NA
  sel <- grepl("ENV",names(d))   ### Adapted from: https://stackoverflow.com/questions/25768305/r-replace-multiple-values-in-multiple-columns-of-dataframes-with-na
  d[sel] <- lapply(d[sel], function(x) replace(x,x %in% 6, NA) )
  
  if (dataset=="UK") {
    ENV_omega <- d %>% select(starts_with("ENV")) %>% omega
    print(paste("ENV omega_h = ", ENV_omega$omega_h))
  }
  ENV_alpha <- d %>% select(starts_with("ENV")) %>% alpha
  print(paste("ENV alpha = ", ENV_alpha$total$raw_alpha))
  
  d <- d %>%
    mutate(ENV_Mean = select(., starts_with("ENV_")) %>%
             rowMeans(na.rm = TRUE))
  
  d$sex[d$sex==1] <- -0.5 # Male
  d$sex[d$sex==2] <- 0.5   # Female
  d$sex[d$sex==3] <- 0  # Prefer not to say/Other
  
  d$z.ENV <- as.vector(scale(d$ENV_Mean, scale=T))
  d$z.PRD <- as.vector(scale(d$PRD_Mean, scale=T))
  d$z.educ <- as.vector(scale(d$educ, scale=T))
  d$z.SSS <- as.vector(scale(d$SSS, scale=T))
  d$z.age <- as.vector(scale(d$age, scale=T))
  d$z.incabs <- as.vector(scale(d$incabs, scale=T))
  
  d$log.incabs <- log10(d$incabs)
  d$z.log.incabs <- as.vector(scale(d$log.incabs, scale=T))
  
  d$SES <- (d$z.educ + d$z.incabs)/2
  d$z.SES <- as.vector(scale(d$SES, scale=T))  
  
  d$f.educ <- factor(d$educ)  # Code education as a factor, with weighted effect coding
  if ((dataset=="US")|(dataset=="US2")) {
    contrasts(d$f.educ) <- contr.wec(d$f.educ, "4") # Use rarest level of education as the omitted category; for US this is top category, for UK it is the lowest
  }  
  if (dataset=="UK") {
    contrasts(d$f.educ) <- contr.wec(d$f.educ, "1") # Use rarest level of education as the omitted category; for US this is top category, for UK it is the lowest
  }  
  
  return(d)
}

inspect_dists <- function(d) { # Have a look at the distributions
  hist(d$incabs, breaks=20, main = "Income")
  hist(d$log.incabs, breaks=20, main = "log Income")
  hist(d$educ, main = "Education")
  hist(d$PRD_Mean, breaks=20, main = "PRD")
  hist(d$ENV_Mean, breaks=20, main = "ENV")
  hist(d$age, breaks=20, main = "Age")
  hist(d$SSS, breaks=20, main="SSS")
}

make_descdat <- function(d) {   # For descriptive statistics and correlation analysis
  descdat <- data.frame(ENV = d$ENV_Mean, PRD=d$PRD_Mean, SSS=d$SSS, INC=d$incabs, EDU=d$educ, AGE=d$age, SEX=d$sex)
  return(descdat)
}

make_regdat <- function(d) {   # It's convenient to have data frames where the z-scored variables are labelled for plots/tables etc
  regdat <- data.frame(ENV=d$z.ENV, PRD=d$z.PRD, SSS=d$z.SSS, AGE=d$z.age, SEX=d$sex, INC=d$z.incabs, EDU=d$z.educ, f.EDU=d$f.educ, SES=d$z.SES, log.INC=d$z.log.incabs)
  return(regdat)
}


get_descriptives <- function(descdat, filename) {   ### Descriptives; format and write to file
  print(table(descdat$SEX))
  descdat <- select(descdat, -SEX)   # Don't include sex -- doesn't make much sense to report mean/SD
  M <- apply(descdat, 2, mean)
  SD <- apply(descdat, 2, sd)
  Min <- apply(descdat, 2, min)
  Max <- apply(descdat, 2, max)
  descstats <- as.data.frame(cbind(M, SD, Min, Max))
  descstats <- cbind(Variable = rownames(descstats), descstats, row.names = NULL)  # Put variable name at start of data frame; get it from the row names, and then set these to NULL
  M_SD <- paste(sprintf("%.2f", descstats$M), " (", sprintf("%.2f", descstats$SD), ")", sep="")
  descstats$M_SD <- M_SD
  descstats <- descstats[c(1,4:6)]
  descstats <- descstats %>% map_df(rev)  # Makes sense to have age at the top, then education etc...
  write.table(descstats, filename, row.names=F)
  ###########
}

### Function for computing correlations
get_correlations <- function(cordat, Analysis="Pearson", Study) {
  varlist <- colnames(cordat)
  nvar <- length(varlist)
  rowctr <- 0    
  cordflist <- list()
  cortype <- ifelse(Analysis=="Pearson", "pearson", "kendall")
  
  for (i in 1:(nvar-1)) {
    for (j in (i+1):nvar) {
      
      rowctr <- rowctr+1
      xvar <- varlist[i]   # Use of x and y is arbitrary  
      yvar <- varlist[j]
      x <- cordat[,xvar]
      y <- cordat[,yvar]
      
      varpair <- paste(xvar, "-", yvar, sep="")
      corres <- cor.test(x,y, method=cortype)
      if (Analysis=="Pearson") {ci <- as.vector(sort(corres$conf.int))}
      if (Analysis=="Kendall") {ci <- as.vector(KendallTauB(x=x, y=y, conf.level = 0.95))[2:3]}   # KendallTauB from DescTools gives a vector: tau_b, CI_lower, CI_upper
      cordflist[[rowctr]] <- c(varpair, corres$estimate, ci[1], ci[2], corres$p.value)
      
    }
  }
  
  cordf = as.data.frame(do.call(rbind, cordflist))
  colnames(cordf) <- c("Parameter", "Coefficient", "CI_low", "CI_high", "p")  # Slightly strange names so that we can easily use the same plotting function as for regression coefficients
  cordf$Analysis <- Analysis
  cordf$Study <- Study
  return(cordf)
}

## Formatting correlation output
format_corr_results <- function(corr_results) {
  corr_results$Coefficient <- as.numeric(corr_results$Coefficient)  # Need to put coefficient and CIs in numeric format
  corr_results$CI_low <- as.numeric(corr_results$CI_low)
  corr_results$CI_high <- as.numeric(corr_results$CI_high)
  corr_results$p <- as.numeric(corr_results$p)
  corr_results$Parameter <- factor(corr_results$Parameter, levels=rev(unique(corr_results$Parameter))) # To get the correlation pairs in a sensible order for the plot
  return(corr_results)
}

### Function for plotting results of correlation and regression analyses
plot_coefficients <- function(curr_coefs, maintitle, showlegend=F, modtype="Reg") {
  
  cbPalette <- c("#E69F00", "#56B4E9", "#009E73", "#0072B2", "#D55E00", "#CC79A7","#F0E442", "#999999", "#000000") # Adapted from: http://www.cookbook-r.com/Graphs/Colors_%28ggplot2%29/
  nAnalyses <- length(unique(curr_coefs$Analysis))
  colourset <- cbPalette[1:nAnalyses]
  symbolset <- c(15:20, 8, 12)[1:nAnalyses]
  
  colourset <- rev(colourset)
  symbolset <- rev(symbolset)
  
  base_size <- 10
  pointsize = 1
  errorbarsize = 0.15
  errorbarwidth <- 0.2
  legend_key_height <- 0.4  # in cm
  ylim=c(-0.40, 0.60)
  yintercept <- 0
  if (modtype=="Corr") {ylim <- c(-0.70, 0.70)}
  leg_pos <- c(0.85, 0.95)
  
  p <- ggplot(curr_coefs, aes(y=Coefficient, x=Parameter, group=Analysis, colour=Analysis, shape=Analysis)) +
    geom_hline(yintercept=yintercept, linetype="dashed", size=0.15) +
    geom_point(position=position_dodge(width=0.3), size=pointsize) +
    geom_errorbar(aes(ymin=CI_low, ymax=CI_high), position = position_dodge(0.3), width=errorbarwidth, size=errorbarsize) +
    scale_shape_manual(values = symbolset) +
    scale_color_manual(values = colourset) +
    theme_bw(base_size=base_size) +
    theme(panel.grid.major = element_blank(), panel.grid.minor = element_blank()) +
    coord_flip() +
    ylab("Estimate") +
    xlab("") +
    ylim(ylim) + 
    theme(axis.text.x = element_text(colour="black", hjust=1),
          axis.text.y = element_text(colour="black")) 
  if (showlegend==F) {p <- p + theme(legend.position = "none")} 
  if (showlegend==T) {
    p <- p + 
      guides(shape = guide_legend(reverse = TRUE), # So the order of the legend matches the order of the points
             color = guide_legend(reverse = TRUE))

      p <- p + 
        theme(legend.position = leg_pos, legend.direction="vertical", legend.title = element_blank(),   # Some stuff for getting rid of white space around legend elements
              legend.key.height = unit(legend_key_height, 'cm'), legend.margin = margin(0, 0, 0, 0), legend.spacing.y = unit(0.2, "pt"))
  }
  
  return(p)
  
}

### Function for fitting models of estimates
fit_regmods <- function(d) {
  
  lm.1 <- lm(ENV ~ SEX + AGE + EDU + INC + SSS + PRD, data=d)
  print(summary(lm.1))
  
  ### Use robust regression
  lmrob.1 <- lmrob(ENV ~ SEX + AGE + EDU + INC + SSS + PRD, data=d, setting="KS2014")
  print(summary(lmrob.1))
  
  ### Check alternative specifications of income/SES, in each case using both OLS and robust regression
  # log-transformed income
  lm.2 <- lm(ENV ~ SEX + AGE + EDU + log.INC + SSS + PRD, data=d)
  print(summary(lm.2))
  
  lmrob.2 <- lmrob(ENV ~ SEX + AGE + EDU + log.INC + SSS + PRD, data=d, setting="KS2014")
  print(summary(lmrob.2))
  
  # SES (average of z-scored income and z-scored education, itself z-scored so 1 unit = 1 SD change in combined SES)
  lm.3 <- lm(ENV ~ SEX + AGE + SES + SSS + PRD, data=d)
  print(summary(lm.3))
  
  lmrob.3 <- lmrob(ENV ~ SEX + AGE + SES + SSS + PRD, data=d, setting="KS2014")
  print(summary(lmrob.3))
  
  # Education as factor
  lm.4 <- lm(ENV ~ SEX + AGE + f.EDU + INC + SSS + PRD, data=d)
  print(summary(lm.4))
  
  lmrob.4 <- lmrob(ENV ~ SEX + AGE + f.EDU + INC + SSS + PRD, data=d, setting="KS2014")
  print(summary(lmrob.4))  
  
  mod_list <- list(lm.1, lm.2, lm.3, lm.4,
                   lmrob.1, lmrob.2, lmrob.3, lmrob.4)
  
  return(mod_list)
  
}


## Function to extract parameters from regression model
get_plotvals <- function(mod) {
  mp <- as.data.frame(model_parameters(mod)) # Get the parameter estimates and CIs into a data frame
  return(mp)
}

get_rsq_vals <- function(mod) {
  summobj <- summary(mod)
  res <- data.frame(rsq=summobj$r.squared, adjrsq=summobj$adj.r.squared)
  return(res)
}

# Function for formatting regression coefficients
get_coefs <- function(curr_mods) {
  cvals <-lapply(curr_mods, get_plotvals) 
  cvals <- bind_rows(cvals, .id = "Analysis")
  rsqvals <- lapply(curr_mods, get_rsq_vals)
  rsqvals <- bind_rows(rsqvals, .id = "Analysis")
  cvals <- merge(cvals, rsqvals)
  cvals$Parameter <- fct_rev(cvals$Parameter) # So Intercept appears first
  cvals$Analysis <- fct_rev(cvals$Analysis) # So Analysis 1 appears first
  print(cvals)
  return(cvals)
}

get_t_rsq_n <- function(summobject) {  # Get values for semi-partial correlation meta-analysis
  summ.df <- as.data.frame(summobject$coefficients)
  summ.df$predictor <- row.names(summ.df)
  t <- summ.df$'t value'[summ.df$predictor=="PRD"]
  rsq <- summobject$r.squared
  npred <- nrow(summ.df) - 1
  spvals <- data.frame(t=t, rsq=rsq, npred=npred)
  return(spvals)
}

get_sp_values <- function(regmods, dataset, dataset_name) {
  regsum <- lapply(regmods, summary)
  sp <- lapply(regsum, get_t_rsq_n)
  sp <- bind_rows(sp, .id = "model")
  sp$n <- nrow(dataset)
  sp$dataset <- dataset_name
  return(sp)
}

### Read in the data
### Call data frames for Studies 1, 2, and 3 dUS, dUK and dUS2, respectively.

dUS <-  read.csv("S1 Data.csv", na.strings=c("","NA"))
print("Applying exclusion criteria: US sample")
dUS <- get_exclusions(d=dUS, dataset="US")

dUK <- read.csv("S2 Data.csv", na.strings=c("","NA"))
print("Applying exclusion criteria: UK sample")
dUK <- get_exclusions(d=dUK, dataset="UK")

dUS2 <- read.csv("S3 Data.csv", na.strings=c("","NA"))
print("Applying exclusion criteria: US_2 sample")
dUS2 <- get_exclusions(d=dUS2, dataset="US2")  

### Construct variables
dUS <- set_incabs(d=dUS)  # incabs = absolute annual income, in thousands
dUS <- make_vars(d=dUS, dataset="US")

dUK <- set_incabs(d=dUK)  
dUK <- make_vars(d=dUK, dataset="UK")

dUS2 <- set_incabs(d=dUS2)
dUS2 <- make_vars(d=dUS2, dataset="US2")
###

par(mfrow=c(4,2))
inspect_dists(dUS)
par(mfrow=c(4,2))
inspect_dists(dUK)
par(mfrow=c(4,2))
inspect_dists(dUS2)

# Descriptive statistics
descdatUS <- make_descdat(dUS)   # It's useful to have data frames that only hold the key variables, for computing correlation matrix etc
get_descriptives(descdat=descdatUS, filename = paste("US_Descriptives.txt", sep=""))

descdatUK <- make_descdat(dUK)
get_descriptives(descdat=descdatUK, filename = paste("UK_Descriptives.txt", sep=""))

descdatUS2 <- make_descdat(dUS2)
get_descriptives(descdat=descdatUS2, filename = paste("US_2_Descriptives.txt", sep=""))

# Correlation analyses
pearson.US <- get_correlations(cordat=descdatUS, Analysis="Pearson", Study="Study 1")
kendall.US <- get_correlations(cordat=descdatUS, Analysis="Kendall", Study="Study 1")

pearson.UK <- get_correlations(cordat=descdatUK, Analysis="Pearson", Study="Study 2")
kendall.UK <- get_correlations(cordat=descdatUK, Analysis="Kendall", Study="Study 2")

pearson.US2 <- get_correlations(cordat=descdatUS2, Analysis="Pearson", Study="Study 3")
kendall.US2 <- get_correlations(cordat=descdatUS2, Analysis="Kendall", Study="Study 3")

corr_results <- rbind(pearson.US, kendall.US, pearson.UK, kendall.UK, pearson.US2, kendall.US2)
corr_results <- format_corr_results(corr_results)
write.csv(corr_results, "S1 Table.csv", row.names=F)   # Write the correlation results to file

##### Put correlations results from all 3 studies on same plot
Pearson_corr_results <- subset(corr_results, Analysis=="Pearson")
Pearson_corr_results$Analysis <- fct_rev(Pearson_corr_results$Study) # This is for the plotting function
pPearson <- plot_coefficients(Pearson_corr_results, maintitle = "Pearson Correlations", showlegend=TRUE, modtype="Corr")
pPearson

ggsave("Fig 1.pdf", plot = pPearson, width = 5.2, height = 6.3, units = "in")
ggsave("Fig 1.tiff", device="tiff", plot = pPearson, width = 5.2, height = 6.3, units = "in")
######################

############################
# Meta-analysis of correlations.
US.r <- cor(descdatUS$ENV, descdatUS$PRD)
UK.r <-  cor(descdatUK$ENV, descdatUK$PRD)
US2.r <-  cor(descdatUS2$ENV, descdatUS2$PRD)
US.n <- nrow(descdatUS)
UK.n <- nrow(descdatUK)
US2.n <- nrow(descdatUS2)

eszcor <- escalc(measure="ZCOR", ri=c(US.r, UK.r, US2.r), ni=c(US.n, UK.n, US2.n))
eszcor
FEmodel<-rma(yi=yi, vi=vi, data=eszcor, method="FE", level=99)
FEmodel
REmodel<-rma(yi=yi, vi=vi, data=eszcor, method="REML", level=99)
REmodel

### Convert back to r scale
transf.ztor(c(FEmodel$b, FEmodel$ci.lb, FEmodel$ci.ub))
transf.ztor(c(REmodel$b, REmodel$ci.lb, REmodel$ci.ub))
##########################################

### Run regression analyses of estimates
############
regdatUS <- make_regdat(d=dUS)
dUS_regmods <- fit_regmods(d=regdatUS)
dUS_coef <- get_coefs(dUS_regmods)

regdatUK <- make_regdat(d=dUK)
dUK_regmods <- fit_regmods(d=regdatUK)
dUK_coef <- get_coefs(dUK_regmods)

regdatUS2 <- make_regdat(d=dUS2)
dUS2_regmods <- fit_regmods(d=regdatUS2)
dUS2_coef <- get_coefs(dUS2_regmods)

### Write the regression coefficients to file
dUS_coef$Study <- "Study_1"
dUK_coef$Study <- "Study_2"
dUS2_coef$Study <- "Study_3"
Collated_Coefs <- rbind(dUS_coef, dUK_coef, dUS2_coef)
write.csv(Collated_Coefs, "S2 Table.csv", row.names=F)
#####

### Plot Analysis 1 grouped by Study
dUS_coef$Study <- "Study 1 (US)"
dUK_coef$Study <- "Study 2 (UK)"
dUS2_coef$Study <- "Study 3 (US)"

Analysis_1 <- rbind(dUS_coef, dUK_coef, dUS2_coef)
Analysis_1 <- subset(Analysis_1, Analysis_1$Analysis==1)
Analysis_1$Analysis <- fct_rev(Analysis_1$Study)
p_Reg_1_by_Study <- plot_coefficients(Analysis_1, maintitle = "Regression Results", showlegend=T)
p_Reg_1_by_Study

### Save plots to pdf files and tiff files (for PLOS ONE)
ggsave("Fig 2.pdf", plot = p_Reg_1_by_Study, width = 5.2, height = 6.3, units = "in")
ggsave("Fig 2.tiff", device="tiff", plot = p_Reg_1_by_Study, width = 5.2, height = 6.3, units = "in")
#####################################

############## Meta-analysis of semi-partial correlations
US_sp <- get_sp_values(regmods=dUS_regmods, dataset=dUS, dataset_name="US")
UK_sp <- get_sp_values(regmods=dUK_regmods, dataset=dUK, dataset_name="UK")
US2_sp <- get_sp_values(regmods=dUS2_regmods, dataset=dUS2, dataset_name="US2")
sp_metavals <- rbind(US_sp, UK_sp, US2_sp)

# There are more elegant ways of doing this...
nmodels <- length(unique(sp_metavals$model))
Reg_REmodels <- data.frame(Analysis=1:nmodels, 
                           Q=numeric(nmodels), Qp=numeric(nmodels),
                           beta=numeric(nmodels), 
                           SE=numeric(nmodels),
                           CI_low=numeric(nmodels), CI_high=numeric(nmodels),
                           p=numeric(nmodels))
for (i in 1:nmodels) {
  sp_vals <- subset(sp_metavals, sp_metavals$model==i)
  sp_es <- escalc(ti=t, ni=n, mi=npred, r2i = rsq, measure="SPCOR", data=sp_vals)
  REmodel <- rma(yi=yi, vi=vi, data=sp_es, method="REML", level=99)
  print(REmodel)
  print(REmodel$p.eff)
  Reg_REmodels$Q[i] <- REmodel$QE
  Reg_REmodels$Qp[i] <- REmodel$QEp
  Reg_REmodels$beta[i] <- REmodel$beta
  Reg_REmodels$SE[i] <- REmodel$se
  Reg_REmodels$CI_low[i] <- REmodel$ci.lb
  Reg_REmodels$CI_high[i] <- REmodel$ci.ub
  Reg_REmodels$p[i] <- REmodel$pval
}
Reg_REmodels
write.csv(Reg_REmodels, "S3 Table.csv", row.names = F)
##################

