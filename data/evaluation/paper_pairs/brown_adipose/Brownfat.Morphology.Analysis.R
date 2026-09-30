## Brown adipose tissue morphology analysis
## Author: Anton S. Becker, M.D.
## Email: 
## Version: 1.0
## Date: 2015-02-22

library(ggplot2)
library(scales) #For %age barplot


# Custom Functions --------------------------------------------------------

# Multiple plot function
#
# ggplot objects can be passed in ..., or to plotlist (as a list of ggplot objects)
# - cols:   Number of columns in layout
# - layout: A matrix specifying the layout. If present, 'cols' is ignored.
#
# If the layout is something like matrix(c(1,2,3,3), nrow=2, byrow=TRUE),
# then plot 1 will go in the upper left, 2 will go in the upper right, and
# 3 will go all the way across the bottom.
#
f.multiplot <- function(..., plotlist=NULL, file, cols=1, layout=NULL) {
  library(grid)
  
  # Make a list from the ... arguments and plotlist
  plots <- c(list(...), plotlist)
  
  numPlots = length(plots)
  
  # If layout is NULL, then use 'cols' to determine layout
  if (is.null(layout)) {
    # Make the panel
    # ncol: Number of columns of plots
    # nrow: Number of rows needed, calculated from # of cols
    layout <- matrix(seq(1, cols * ceiling(numPlots/cols)),
                     ncol = cols, nrow = ceiling(numPlots/cols))
  }
  
  if (numPlots==1) {
    print(plots[[1]])
    
  } else {
    # Set up the page
    grid.newpage()
    pushViewport(viewport(layout = grid.layout(nrow(layout), ncol(layout))))
    
    # Make each plot, in the correct location
    for (i in 1:numPlots) {
      # Get the i,j matrix positions of the regions that contain this subplot
      matchidx <- as.data.frame(which(layout == i, arr.ind = TRUE))
      
      print(plots[[i]], vp = viewport(layout.pos.row = matchidx$row,
                                      layout.pos.col = matchidx$col))
    }
  }
}




# Analysis ----------------------------------------------------------------

d.brownfat <- read.csv('bat.morphology.anonymized.csv')

d.active <- subset(d.brownfat, d.brownfat$Readout.bat == 1)

# Create Subsets of male/female
d.bffem <- subset(d.brownfat, d.brownfat$Sex == 'female')
d.bfmal <- subset(d.brownfat, d.brownfat$Sex != 'female')
d.activefem <- subset(d.active, d.active$Sex == 'female')
d.activemal <- subset(d.active, d.active$Sex != 'female')

# Age Histogram Fused:
BAT <- chartr('10', 'yn', d.brownfat$Readout.bat)
BAT <- as.factor(BAT)
ggplot(d.brownfat, aes(x=Age.y, fill=BAT)) + geom_density(alpha=.3) + labs(x="Age")

# BMI Histogram Fused:
ggplot(d.brownfat, aes(x=BMI, fill=BAT)) + geom_density(alpha=.3)

## Barplot Gender
levels(BAT) <- c('none','active')
ggplot(d.brownfat, aes(x=Sex, fill=BAT)) + 
  geom_bar(position = "fill") + 
  scale_y_continuous(labels = percent_format()) +
  coord_cartesian(ylim=c(0.85,1)) +
  labs(x = "Sex", y = "Percentage")

ggplot(d.active, aes(x=Sex)) + 
  geom_bar() + 
  labs(x = "Sex", y = "Number of Cases")

## Boxplot Temp
qplot(BAT, d.brownfat$Temperature.C, geom="boxplot",
      fill=BAT, main="Active BAT",
      xlab="", ylab="Daily Temperature")

# Labelling 
BATd.labels <- c("None","Supraclavicular", "Mediastinal", "Infradiaphragmatic")
batlvl <- c(0:3)
d.brownfat$BATd <- factor(d.brownfat$BAT.Distribution, levels = batlvl, labels = BATd.labels)
fourcols <- c("#c581fd", "#f8766d" , "#1cba38", "#619bfc")

BATd.labels2 <- c("Supraclavicular", "Mediastinal", "Infradiaphragmatic")
batlvl2 <- c(1:3)
d.active$BATd <- factor(d.active$BAT.Distribution, levels = batlvl2, labels = BATd.labels2)

## Boxplot Temp - Distribution

box.distr.temp <- qplot(d.brownfat$BATd, d.brownfat$Temperature.C, geom="boxplot",
                        fill=d.brownfat$BATd, #main="BAT distribution",
                        xlab="", ylab="Temperature") + 
  scale_fill_manual(values = fourcols) +
  theme(legend.position = "none")

## Boxplot BMI - Distribution
box.distr.bmi <- qplot(d.brownfat$BATd, d.brownfat$BMI, geom="boxplot",
                       fill=d.brownfat$BATd, #main="BAT distribution",
                       xlab="", ylab="BMI") +
  scale_fill_manual(values = fourcols) +
  geom_smooth(method = "lm", se=FALSE, color="black", alpha = 0.15, aes(group=1), linetype=6) +
  theme(legend.position = "none")

## Boxplot Age - Distribution
box.distr.age <- qplot(d.brownfat$BATd, d.brownfat$Age.y, geom="boxplot",
                       fill=d.brownfat$BATd, #main="BAT distribution",
                       xlab="", ylab="Age") +
  scale_fill_manual(values = fourcols) +
  geom_smooth(method = "lm", se=FALSE, color="black", aes(group=1), linetype=6) +
  theme(legend.position = "none")

## Barplot (Sex -) Distribution
d.active$BATd2 <- factor(d.active$BAT.Distribution, levels = batlvl2, labels = BATd.labels2)

bar.distr.sex <- ggplot(d.active, aes(Sex, fill = factor(BATd2))) + geom_bar() +
  ylab("Number of Cases") + xlab("Sex") +
  theme(legend.position = "none") +
  facet_grid(. ~ BATd)

bar.distr <- ggplot(d.active, aes(BATd, fill = factor(BATd2))) + geom_bar() +
  ylab("Number of Cases") + xlab("") +
  theme(legend.position = "none") +
  coord_flip() + scale_x_discrete(limits = rev(levels(d.active$BATd2)))


## Plots Quantitative Readouts
bp.tlg.m <- qplot(d.active$BATd2, d.active$BAT.TLG, geom="boxplot",
                  fill=d.active$BATd2, main="",
                  xlab="", ylab="Total Fat Glycolysis (TFG)") +
                  theme(legend.position = "none") #+
       #coord_flip() + scale_x_discrete(limits = rev(levels(d.active$BATd2)))

bp.suvmax.m <- qplot(d.active$BATd2, d.active$BAT.FDG.activity.SUVmax, geom="boxplot",
                     fill=d.active$BATd2, main="",
                     xlab="", ylab="SUVmax") +
                     theme(legend.position = "none") #+
    #coord_flip() + scale_x_discrete(limits = rev(levels(d.active$BATd2)))

bp.vol.m <- qplot(d.active$BATd2, d.active$BAT.MTV.cm3, geom="boxplot", 
                  fill=d.active$BATd2) +
                  ylab(expression(paste("Total Volume (", cm^3, ")", sep = ""))) +
                  xlab("") +
                  theme(legend.position = "none") #+
           #coord_flip() + scale_x_discrete(limits = rev(levels(d.active$BATd2)))

multiplot(bp.vol.m, bp.tlg.m, bp.suvmax.m, cols=3)


## Histogram TLG
ggplot(data = d.active, aes(d.active$BAT.TLG)) + geom_histogram()

##  Temp ~ TLG
dp.tlg.temp <- ggplot(data = d.active, aes(BAT.TLG, Temperature.C, 
                                           colour = factor(BATd2))) + 
                      geom_point() +
                      theme(legend.justification=c(1,0), legend.position=c(1,0)) +  
                      xlab("Total Fat Glycolysis (TFG)") +
                      ylab("Temperature") +
                      labs(color = "Anatomical Distribution") 

## BMI ~ TLG
dp.tlg.bmi <- ggplot(data = d.active, aes(BAT.TLG, BMI, 
                                          colour = factor(BATd2))) + 
              geom_point() +
              theme(legend.position="none") +
              xlab("Total Fat Glycolysis (TFG)") +
              ylab("BMI") +
              labs(color = "Anatomical Distribution") 

## Age.y ~ TLG
dp.tlg.age <- ggplot(data = d.active, aes(BAT.TLG, Age.y, 
                                          colour = factor(BATd2))) + 
              geom_point() +
              theme(legend.position="none") +
              xlab("Total Fat Glycolysis (TFG)") +
              ylab("Age") +
              labs(color = "Anatomical Distribution") 

multiplot(dp.tlg.bmi, dp.tlg.age, dp.tlg.temp, box.distr.bmi, box.distr.age, box.distr.temp, cols = 2) 


# Significance tests ------------------------------------------------------

# BAT - Temperature
t.test(d.brownfat[which(d.brownfat$Readout.bat == 0),]$Temperature.C, 
       d.brownfat[which(d.brownfat$BAT.Distribution > 1), ]$Temperature.C)

t.test(Age.y ~ Readout.bat, data = d.brownfat)
t.test(BMI ~ Readout.bat, data = d.brownfat)
t.test(Temperatur ~ Readout.bat, data = d.brownfat)

# Comp. Sex whole Pop.
t.test(Age.y ~ Sex, data = d.brownfat)
plot(Age.y ~ Sex, data = d.brownfat)

t.test(BMI ~ Sex, data = d.brownfat)
plot(BMI ~ Sex, data = d.brownfat)

# BAT+ pat.
t.test(Age.y ~ Sex, data = d.active)
plot(Age.y ~ Sex, data = d.active)

t.test(BMI ~ Sex, data = d.active)
plot(BMI ~ Sex, data = d.active)

# Linear fitting of BAT-Distribution
fit <- lm(BAT.Distribution ~ Age.y+BMI*Temperature.C, data=d.brownfat)

anova(fit)
