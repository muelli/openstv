#!/usr/bin/env python
# "run an election from the command line with optional profiling"

# __revision__ = "$Id: runElection.py 715 2010-02-27 17:00:55Z jeff.oneill $"

import sys
import os
import re

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import getopt
import shutil

from openstv.ballots import Ballots
from openstv.plugins import getMethodPlugins, getReportPlugins

methods = getMethodPlugins("byName", exclude0=False)
methodNames = methods.keys()
methodNames.sort()

reports = getReportPlugins("byName", exclude0=False)
reportNames = reports.keys()
reportNames.sort()

usage = """
Usage:

  runRanking.py [-p prec] [-r report] [-t tiebreak] [-w weaktie] 
                 [-P] [-x reps] method ballotfile

  -p: override default precision (in digits)
  -r: report format: %s
  -t: strong tie-break method: random*, alpha, index
  -w: weak tie-break method: (method-default)*, strong, forward, backward 
  -P: profile and send output to profile.out
  -x: specify repeat count (for profiling)
    *default

  Runs an election for the given method and ballot file. Results are
  printed to stdout. The following methods are available:
%s
""" % (", ".join(reportNames),
       "\n".join(["    " + name for name in methodNames]))

# Parse the command line.
try:
  (opts, args) = getopt.getopt(sys.argv[1:], "Pp:r:l:t:w:x:")
except getopt.GetoptError, err:
  print str(err) # will print something like "option -a not recognized"
  print usage
  sys.exit(1)

profile = False
reps = 1
reportformat = "HtmlReport"
strongTieBreakMethod = None
weakTieBreakMethod = None
numSeats = None
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
  if o == "-s":
    print "Seats option unsupported when ranking"
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


blankLineRE = re.compile(r'^\s*(?:#.*)?$')
nCandnSeatsRE = re.compile(r'^\s*(\d+)\s+(\d+)\s*(?:#.*)?$')
withdrawnRE = re.compile(r'^\s*(-\d+(?:\s+-\d+)*)\s*(?:#.*)?$')
ballotRE = re.compile(r'^\s*(\d+(?:\s+[\d\-=]+)*)\s+0\s*(?:#.*)?$')
ballotAndIDRE = re.compile(r'^\s*\(([^\)]+)\)\s+(\d+(?:\s+[\d\-=]+)*)\s+0\s*(?:#.*)?$')
endOfBallotsRE = re.compile(r'\s*0\s*(?:#.*)?')
stringRE = re.compile(r'^\s*"([^"]+)"\s*(?:#.*)?$')

baseFileName = os.path.splitext(bltFn)[0]
extension = os.path.splitext(bltFn)[1]

BALLOTS_DIR = 'ballots/'

def updateBallots(cleanBallots, excluded, rank):
  if not os.path.exists('ballots'):
    os.makedirs('ballots')

  # Sanity check
  if cleanBallots.numSeats != rank - 1: 
    print "ERROR: something went wrong", cleanBallots.numSeats, rank

  copy = cleanBallots.copy()
  copy.numSeats = (cleanBallots.numSeats - 1)
  copy.saveAs(BALLOTS_DIR + baseFileName + ".tmp")

  newLines = []
  candidateIndex = 0
  for line in open(BALLOTS_DIR + baseFileName + ".tmp"):
    out = nCandnSeatsRE.match(line)
    if out is not None: 
      newLines.append(str(cleanBallots.getNumCandidates() - 1) + " " + str(rank - 1) + "\n")
      continue

    out = ballotAndIDRE.match(line)
    if out is not None:
      ballotIndex = out.group(1)
      rankings = out.group(2).split()[1:]
      if str(excluded) in rankings:
        rankings.remove(str(excluded))

      newRankings = map(lambda c: c if (int(c) < excluded) else str(int(c) -1), rankings)

      newLine = "(" + ballotIndex +") 1 "
      for vote in newRankings:
        newLine += str(vote) + " "
      newLine += "0\n"
      newLines.append(newLine)

      continue

    out = stringRE.match(line)
    if out is not None:
      if candidateIndex != -1: # excluded candidate not met yet
        if candidateIndex == excluded:
          candidateIndex = -1
          continue # Skip this candidate since they have been excluded
        else:
          candidateIndex += 1

    newLines.append(line)


  os.remove(BALLOTS_DIR + baseFileName + ".tmp")
  f  = open(BALLOTS_DIR + baseFileName + "." + str(rank - 1) + extension, 'w+')
  f.writelines(newLines)
  f.close()


def doElection(reps=1):
  "run election with repeat count for profiling"
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


firstRound = True
initialCandidates, candidates = ([],)*2
finalRanking = {}

## This is a bit redundant
dirtyBallots = Ballots()
dirtyBallots.loadKnown(bltFn, exclude0=False)
lastRank = dirtyBallots.getCleanBallots().getNumCandidates()
initialCandidates = set(range(0, lastRank))

for rank in range(lastRank, 0, -1):
  try:
    if not firstRound:
      bltFn = 'ballots/'+baseFileName+ "." + str(rank) + extension

    dirtyBallots = Ballots()
    dirtyBallots.loadKnown(bltFn, exclude0=False)
    dirtyBallots.numSeats = rank - 1
    cleanBallots = dirtyBallots.getCleanBallots()

    if firstRound: 
      candidates = initialCandidates
      firstRound = False

  except RuntimeError, msg:
    print msg
    sys.exit(1)

  if profile:
    cProfile.run('e = doElection(reps)', profilefile)
  else:
    e = doElection()
  
  print "<h3>Round %d</h3>" % (lastRank - rank + 1)
  r = reports[reportformat](e)
  r.generateReport()
  
  if profile:
    p = pstats.Stats(profilefile)
    p.strip_dirs().sort_stats('time').print_stats(50)

  eliminatedSet = candidates.difference(e.winners)
  if len(eliminatedSet) > 1:
    print "More than ONE candidate eliminated:", candidates.difference(e.winners)
    sys.exit(1)

  eliminated = eliminatedSet.pop()
  eliminatedName = cleanBallots.getNames()[eliminated]
  finalRanking[rank] = eliminatedName

  
  roundLine = """\
  --
    Rank: %d
    Eliminated: %s (index in file %s: %d)\
  """ % (rank, eliminatedName, bltFn,eliminated)
  print roundLine

  candidates = set(map(lambda c: c if (c < eliminated) else c - 1, e.winners))
  if len(candidates) == 1: # one candidate is left, they are ranked #1
    # print "Winner - Rank 1\n"
    winner = e.winners.pop()
    winnerName = cleanBallots.getNames()[winner]
    # roundLine = """\
    # --
    #   Rank: 1
    #   Winner: %s (index in file %s: %d)\
    # """ % (winnerName, bltFn, winner)
    # print roundLine    
    finalRanking[1] = winnerName
    break;
  else:
    updateBallots(cleanBallots, eliminated, rank)

print """<br>
  <h3>Final Ranking</h3>
  <table class="rounds">
    <tr>
      <th>Rank</th>
      <th>Candidate</th>
    </tr>
"""
for rank in finalRanking:
  print "<tr><td>%d</td><td>%s</td></tr>" % (rank, finalRanking[rank])
print "</table>"