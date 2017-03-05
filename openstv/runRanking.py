#!/usr/bin/env python
"run a ranking from the command line with optional profiling"

import sys
import os
import re

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import getopt

from openstv.ballots import Ballots
from openstv.plugins import getMethodPlugins, getReportPlugins

methods = getMethodPlugins("byName", exclude0=False)
methodNames = methods.keys()
methodNames.sort()

reports = getReportPlugins("byName", exclude0=False)
reportNames = reports.keys()
reportNames.sort()


""" Util REGEX to read a BLT file line by line """
blankLineRE = re.compile(r'^\s*(?:#.*)?$')
nCandnSeatsRE = re.compile(r'^\s*(\d+)\s+(\d+)\s*(?:#.*)?$')
withdrawnRE = re.compile(r'^\s*(-\d+(?:\s+-\d+)*)\s*(?:#.*)?$')
ballotRE = re.compile(r'^\s*(\d+(?:\s+[\d\-=]+)*)\s+0\s*(?:#.*)?$')
ballotAndIDRE = re.compile(r'^\s*\(([^\)]+)\)\s+(\d+(?:\s+[\d\-=]+)*)\s+0\s*(?:#.*)?$')
endOfBallotsRE = re.compile(r'\s*0\s*(?:#.*)?')
stringRE = re.compile(r'^\s*"([^"]+)"\s*(?:#.*)?$')


""" tmp folder for intermediate ballot files """
BALLOTS_DIR = 'tmp_ballots/'
genTmpBallots = False

usage = """
Usage:

  runElection.py [-p prec] [-r report] [-t tiebreak] [-w weaktie] [-s seats] 
                 [-P] [-D] [-x reps] method ballotfile

  -p: override default precision (in digits)
  -r: report format: %s
  -t: strong tie-break method: random*, alpha, index
  -w: weak tie-break method: (method-default)*, strong, forward, backward 
  -P: profile and send output to profile.out
  -D: generate intermediate ballots for ranking iteration
  -x: specify repeat count (for profiling)
    *default

  Runs a ranking for the given method and ballot file. Results are
  printed to stdout. The following methods are available:
%s
""" % (", ".join(reportNames),
       "\n".join(["    " + name for name in methodNames]))


# Parse the command line.
try:
  (opts, args) = getopt.getopt(sys.argv[1:], "DPp:r:t:w:x:")
except getopt.GetoptError, err:
  print str(err) # will print something like "option -a not recognized"
  print usage
  sys.exit(1)

profile = False
reps = 1
reportformat = "NoReport"
strongTieBreakMethod = None
weakTieBreakMethod = None
#numSeats = None
prec = None
for o, a in opts:
  if o == "-r":
    if a in reportNames:
      reportformat = a
    else:
      print "Unrecognized report format '%s'" % a
      print usage
      sys.exit(1)
  if o == "-p":
    prec = int(a)
  # if o == "-s":
  #   numSeats = int(a)
  if o == "-t":
    if a in ["random", "alpha", "index"]:
      strongTieBreakMethod = a
    else:
      print "Unrecognized tie-break method '%s'" % a
      print usage
      sys.exit(1)
  if o == "-w":
    if a in ["strong", "forward", "backward"]:
      weakTieBreakMethod = a
    else:
      print "Unrecognized weak tie-break method '%s'" % a
      print usage
      sys.exit(1)
  if o == "-P":
    import cProfile
    import pstats
    profile = True
    profilefile = "profile.out"
  if o == "-x":
    reps = int(a)
  if o == "-D":
    genTmpBallots = True

if len(args) != 2:
  if len(args) < 2:
    print "Specify method and ballot file"
  else:
    print "Too many arguments"
  print usage
  sys.exit(1)

name = args[0]
bltFn = args[1]

if name not in methodNames:
  print "Unrecognized method '%s'" % name
  print usage
  sys.exit(1)


def doElection(cleanBallots, reps=1):
  """ run election with repeat count for profiling """
  for i in xrange(reps):
    e = methods[name](cleanBallots)
    if strongTieBreakMethod is not None:
      e.strongTieBreakMethod = strongTieBreakMethod
    if weakTieBreakMethod is not None:
      e.weakTieBreakMethod = weakTieBreakMethod
    if prec is not None:
      e.prec = prec
    e.runElection()
  return e


def alterBallots(ballots, loser):
  """ 
    Alter ballots by removing votes for the loser candidate

    ballots: Current ballots object
    loser: index of last eliminated candidate in current ballot
  """

  nextRank = ballots.getNumCandidates() - 1
  seats = ballots.getNumCandidates() - 2

  if not os.path.exists(BALLOTS_DIR):
    os.makedirs(BALLOTS_DIR)

  tmpFile = BALLOTS_DIR + "_tmp.blt"

  copy = ballots.copy()
  copy.numSeats = (ballots.numSeats - 1)
  copy.saveAs(tmpFile)

  newLines = []
  candidateIndex = 0
  for line in open(tmpFile):
    out = nCandnSeatsRE.match(line)

    """ 
      Append the first line of the new ballot file:
      #Candidates #Seats 
    """
    if out is not None: 
      newLines.append(str(nextRank) + " " + str(seats) + "\n")
      continue


    """
      Alter old ballots by removing votes for excluded candidate
      (index) 1 # # # # # 0 \n
    """
    out = ballotAndIDRE.match(line)
    if out is not None:
      ballotIndex = out.group(1)
      rankings = out.group(2).split()[1:]
      if str(loser) in rankings:
        rankings.remove(str(loser))

      """ 
        apply a lambda function to "bump" candidates that were ranked below the excluded candidate,
        other candidates keep their original rank
      """
      newRankings = map(lambda c: c if (int(c) < loser) else str(int(c) -1), rankings)

      newLine = "(" + ballotIndex +") 1 "
      for vote in newRankings:
        newLine += str(vote) + " "
      newLine += "0\n"
      newLines.append(newLine)

      continue

    """ 
      Remove excluded candidate name
    """
    out = stringRE.match(line)
    if out is not None:
      if candidateIndex != -1: # excluded candidate not met yet
        if candidateIndex == loser - 1: ## Candidate names are 0-indexed !!!!!!
          candidateIndex = -1
          continue # Skip this candidate since they have been excluded
        else:
          candidateIndex += 1

    """
      Append the rest of candidate names to the new file
    """
    newLines.append(line)


  """ 
    write file
  """
  os.remove(tmpFile)
  newFileName = BALLOTS_DIR + "_.%s.blt" % str(nextRank) 
  f  = open(newFileName, 'w+')
  f.writelines(newLines)
  f.close()
  
  dirtyBallots = Ballots()
  dirtyBallots.loadKnown(newFileName, exclude0=False)
  return dirtyBallots

def printRank(rank, candidate):
  if (reportformat == 'HtmlReport'):
    print '<h3>%d - %s</h3>' % (rank, candidate)
  else:
    print '%d - %s' % (rank, candidate)

def withdraweCandidates(currentBallots, withdrawn):
  """ Alter ballots by withdrawing excluded candidates """
  dirtyTmpBallots = Ballots()
  dirtyTmpBallots.loadKnown(bltFn, exclude0=False)
  dirtyTmpBallots.numSeats = currentBallots.numSeats - 1
  dirtyTmpBallots.withdrawn = withdrawn
  return dirtyTmpBallots.getCleanBallots()

try:

  # Prepare list for excluded candidate
  withdrawn = []

  dirtyBallots = Ballots()
  dirtyBallots.loadKnown(bltFn, exclude0=False)
  dirtyBallots.numSeats = dirtyBallots.getNumCandidates() - 1 
  currentBallots = dirtyBallots.getCleanBallots()
  initalNames = currentBallots.getNames()
  rank = dirtyBallots.numSeats + 1

  if (reportformat == 'HtmlReport'):
    print '<h1>%s</h1>' % currentBallots.title

  currentBallots.title = 'Round %d' % rank

  while True:
    e = doElection(currentBallots)

    if reportformat != 'NoReport':
      r = reports[reportformat](e)
      r.generateReport()

    loser = e.losers.pop()
    excludedName = currentBallots.getNames()[loser]

    excludedIndex = 0
    for i in xrange(len(initalNames)):
      if initalNames[i] == excludedName:
        excludedIndex = i

    printRank(rank, excludedName)
    if (len(e.winners) == 1):
      printRank(rank - 1, currentBallots.getNames()[e.winners.pop()])
      break

    if excludedIndex in withdrawn:
      print 'ERROR', excludedIndex, 'was already excluded'
      sys.exit(1)
    else:
      withdrawn.append(excludedIndex)

    if genTmpBallots:
      currentBallots = alterBallots(currentBallots, loser + 1) ## ballots are 1-indexed !!!!
    else:      
      currentBallots = withdraweCandidates(currentBallots, withdrawn)
      currentBallots.title = 'Round %d' % int(currentBallots.getNumCandidates())

    rank -= 1


except RuntimeError, msg:
  print msg
  sys.exit(1)


# if profile:
#   cProfile.run('e = doElection(reps)', profilefile)
# else:
#   e = doElection()

# r = reports[reportformat](e)
# r.generateReport()

# if profile:
#   p = pstats.Stats(profilefile)
#   p.strip_dirs().sort_stats('time').print_stats(50)
