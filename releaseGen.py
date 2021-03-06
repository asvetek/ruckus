#!/usr/bin/env python3
#-----------------------------------------------------------------------------
# Title      : Release Generation
# ----------------------------------------------------------------------------
# Description:
# Script to generate rogue.zip and cpsw.tar.gz files as well as creating 
# a github release with proper release attachments.
# ----------------------------------------------------------------------------
# This file is part of the 'SLAC Firmware Standard Library'. It is subject to 
# the license terms in the LICENSE.txt file found in the top-level directory 
# of this distribution and at: 
#    https://confluence.slac.stanford.edu/display/ppareg/LICENSE.html. 
# No part of the 'SLAC Firmware Standard Library', including this file, may be 
# copied, modified, propagated, or distributed except according to the terms 
# contained in the LICENSE.txt file.
# ----------------------------------------------------------------------------

import os
import yaml
import argparse
import zipfile
import tarfile

import git    # GitPython
import github # PyGithub

import re
from getpass import getpass
import releaseNotes

# Set the argument parser
parser = argparse.ArgumentParser('Release Generation')

# Add arguments
parser.add_argument(
    "--project", 
    type     = str,
    required = True,
    help     = "Project directory path"
)

parser.add_argument(
    "--release", 
    type     = str,
    required = False,
    default  = None,
    help     = "Release target to generate"
)

parser.add_argument(
    "--build", 
    type     = str,
    required = False,
    default  = None,
    help     = "Build base name to include (for single target release), 'latest' to auto select"
)

parser.add_argument(
    "--version", 
    type     = str,
    required = False,
    default  = None,
    help     = "Version value for release."
)

parser.add_argument(
    "--prev", 
    type     = str,
    required = False,
    default  = None,
    help     = "Previous version for release notes comparison."
)

parser.add_argument(
    "--user", 
    type     = str, 
    required = False,
    default  = None,
    help     = "Username for github"
)

parser.add_argument(
    "--password",
    type     = str, 
    required = False,
    default  = None,
    help     = "Password for github"
)

parser.add_argument(
    "--push", 
    action   = 'count',
    help     = "Add --push arg to tag repository and push release to github"
)

# Get the arguments
args = parser.parse_args()

# Directories
FirmwareDir = os.path.join(args.project, 'firmware')

def loadReleaseConfig():
    relFile = os.path.join(FirmwareDir,'releases.yaml')

    try:
        with open(relFile) as f:
            txt = f.read()
            cfg = yaml.load(txt)
    except Exception as e:
        raise Exception(f"Failed to load project release file {relFile}")

    if not 'Releases' in cfg or cfg['Releases'] is None:
        raise Exception("Invalid release config. Releases key is missing or empty!")

    if not 'Targets' in cfg or cfg['Targets'] is None:
        raise Exception("Invalid release config. Targets key is missing or empty!")

    return cfg

def getVersion():
    ver  = args.version
    prev = args.prev

    if ver is None:
        ver = input('\nEnter version for release (i.e. v1.2.3): ')

    if args.push is not None:
        if prev is None:
            prev = input('\nEnter previous version for compare (i.e. v1.2.3): ')

    print(f'\nUsing version {ver} and previous version {prev}\n')

    return ver, prev

def selectRelease(cfg):

    relName = args.release

    print("")
    print("Available Releases:")

    keyList = list(cfg['Releases'].keys())

    for idx,val in enumerate(keyList):
        print(f"    {idx}: {val}")

    if relName is not None:
        print(f"\nUsing command line arg release: {relName}")

        if relName not in keyList:
            raise Exception(f"Invalid command line release arg: {relName}")

    elif len(keyList) == 1:
        relName = keyList[0]
        print(f"\nAuto selecting release: {relName}")

    else:
        idx = int(input('\nEnter index ot release to generate: '))

        if idx >= len(keyList):
            raise Exception("Invalid release index")

        else:
            relName = keyList[idx]

    relData = cfg['Releases'][relName]

    if not 'Targets' in relData or relData['Targets'] is None:
        raise Exception(f"Invalid release config. Targets list in release {relName} is missing or empty!")

    if not 'Types' in relData or relData['Types'] is None:
        raise Exception(f"Invalid release config. Types list in release {relName} is missing or empty!")

    return relName, relData

def selectBuildImages(cfg, relName, relData):
    retList = []

    for target in relData['Targets']:
        imageDir = os.path.join(FirmwareDir,'targets',target,'images')

        if not target in cfg['Targets']:
            raise Exception(f"Invalid release config. Referenced target {target} is missing in target list.!")

        if not 'Extensions' in cfg['Targets'][target] or cfg['Targets'][target]['Extensions'] is None:
            raise Exception(f"Invalid release config. Extensions list for target {target} is missing or empty!")

        extensions = cfg['Targets'][target]['Extensions']

        buildName = args.build
        dirList = [f for f in os.listdir(imageDir) if os.path.isfile(os.path.join(imageDir,f))]

        print(f"\nFinding builds for target {target}:")

        # Get a list of images
        baseList = set()

        for fn in dirList:
            if target in fn:
                baseList.add(fn.split('.')[0])

        sortList = sorted(baseList)
        for idx,val in enumerate(sortList):
            print(f"    {idx}: {val}")

        if buildName == 'latest':
            buildName = sortList[-1]
            print(f"\nAuto selecting latest build: {buildName}")

        elif buildName is not None:
            print(f"\nUsing command line arg build: {buildName}")

            if buildName not in sortList:
                raise Exception(f"Invalid command line build arg: {buildName}")

        else:
            idx = int(input('\nEnter index of build to include for target {}: '.format(target)))

            if idx >= len(sortList):
                raise Exception("Invalid build index")

            else:
                buildName = sortList[idx]

        tarList = [f'{buildName}.{ext}' for ext in extensions]

        print(f"\nFinding images for target {target}, build {buildName}...")
        for f in dirList:
            if f in tarList:
                retList.append(os.path.join(imageDir,f))

    return retList

def genFileList(base,root,entries,typ):
    retList = []

    for e in entries:
        fullPath = os.path.join(root,e)
        subPath  = fullPath.replace(base+'/','')

        retList.append({'type':typ,
                        'fullPath':fullPath,
                        'subPath': subPath})
    return retList

def selectFiles(cfg, relData, key):
    dirList = []
    retList = []

    # Generic files
    if key in cfg and cfg[key] is not None:
        dirList.extend(cfg[key])

    # Release specific files
    if key in relData and relData[key] is not None:
        dirList.extend(relData[key])

    for d in dirList:
        base = os.path.join(FirmwareDir,d)

        for root, folders, files in os.walk(base):
            retList.extend(genFileList(base,root,folders,'folder'))
            retList.extend(genFileList(base,root,files,'file'))

    return retList

def buildRogueFile(zipName, cfg, ver, relName, relData, imgList):
    print("\nFinding Rogue Files...")
    pList = selectFiles(cfg, relData, 'RoguePackages')
    cList = selectFiles(cfg, relData, 'RogueConfig')

    if len(pList) == 0:
        raise Exception(f"Invalid release config. Rogue packages list is empty!")

    if not 'TopPackage' in cfg or cfg['TopPackage'] is None:
        raise Exception("Invalid release config. TopPackage is not defined!")

    # setuptools version creates and installs a .egg file which will not work with
    # our image and config data! Use distutils version for now.
    setupPy  =  "\n\nfrom distutils.core import setup\n\n"
    #setupPy  =  "\n\nfrom setuptools import setup\n\n"
    setupPy +=  "setup (\n"
    setupPy += f"   name='{relName}',\n"
    setupPy += f"   version='{ver}',\n"
    setupPy +=  "   packages=[\n"

    topInit = cfg['TopPackage'] + '/__init__.py'
    topPath = None

    with zipfile.ZipFile(zipName,'w') as zf:
        print(f"\nCreating Rogue zipfile {zipName}")

        for e in pList:
            dst = e['subPath']

            # Don't add raw version of TopPackage/__init__.py
            if e['subPath'] == topInit:
                topPath = e['fullPath']
            else:
                zf.write(e['fullPath'],dst)

            if e['type'] == 'folder':
                setupPy +=  "             '{}',\n".format(dst)

        setupPy +=  "            ],\n"

        for e in cList:
            dst = cfg['TopPackage'] + '/config/' + e['subPath']
            zf.write(e['fullPath'],dst)

        for e in imgList:
            dst = cfg['TopPackage'] + '/images/' + os.path.basename(e)
            zf.write(e,dst)

        # Generate setup.py payload
        setupPy +=  "   package_data={'" + cfg['TopPackage'] + "':['config/*','images/*']}\n"
        setupPy += ")\n"

        with zf.open('setup.py','w') as sf: sf.write(setupPy.encode('utf-8'))

        with open(topPath,'r') as f:
            newInit = ""

            for line in f:
                if (not 'import os'   in line) and \
                   (not '__version__' in line) and \
                   (not 'ConfigDir'   in line) and \
                   (not 'ImageDir'    in line): newInit += line

        # Append new lines
        newInit += "\n\n"
        newInit += "##################### Added by release script ###################\n"
        newInit += "import os\n"
        newInit += f"__version__ = '{ver}'\n"
        newInit += "ConfigDir = os.path.dirname(__file__) + '/config'\n"
        newInit += "ImageDir  = os.path.dirname(__file__) + '/images'\n"
        newInit += "#################################################################\n"

        with zf.open(topInit,'w') as f:
            f.write(newInit.encode('utf-8'))

def buildCpswFile(tarName, cfg, ver, relName, relData, imgList):
    print("\nFinding CPSW Files...")
    sList = selectFiles(cfg, relData, 'CpswSource')
    cList = selectFiles(cfg, relData, 'CpswConfig')

    baseDir = relName + '_project.yaml'

    if len(sList) == 0:
        raise Exception(f"Invalid release config. Cpsw packages list is empty!")

    with tarfile.open(tarName,'w:gz') as tf:
        print(f"\nCreating CPSW tarfile {tarName}")

        for e in sList:
            if e['type'] == 'file':
                tf.add(name=e['fullPath'],arcname=baseDir+'/'+e['subPath'],recursive=False)

        for e in cList:
            if e['type'] == 'file':
                tf.add(name=e['fullPath'],arcname=baseDir+'/config/'+e['subPath'],recursive=False)

def pushRelease(relName, ver, tagAttach, prev):
    locRepo = git.Repo(args.project)

    url = locRepo.remote().url
    if not url.endswith('.git'): url += '.git'

    project = re.compile(r'slaclab/(?P<name>.*?)(?P<ext>\.git?)').search(url).group('name')

    if locRepo.is_dirty():
        raise(Exception("Cannot create tag! Git repo is dirty!"))

    tag = f'{relName}_{ver}'
    msg = f'{relName} version {ver}'

    print(f"\nCreating and pushing tag {tag} .... ")
    newTag = locRepo.create_tag(path=tag, message=msg)
    locRepo.remotes.origin.push(newTag)

    print("\nLogging into github....")

    if args.user is None:
        username = input("Username for github: ")
    else:
        username = args.user

    if args.password is None:
        password = getpass("Password for github: ")
    else:
        password = args.password

    tagRange = f'{relName}_{prev}..{relName}_{ver}'

    gh = github.Github(username,password)
    remRepo = gh.get_repo(f'slaclab/{project}')

    print("\nGenerating release notes ...")
    md = releaseNotes.getReleaseNotes(git.Git(args.project), remRepo, tagRange)
    remRel = remRepo.create_git_release(tag=tag,name=msg, message=md, draft=False)

    print("\nUploading attahments ...")
    for t in tagAttach:
        remRel.upload_asset(t)


if __name__ == "__main__":
    cfg = loadReleaseConfig()
    relName,relData = selectRelease(cfg)
    imgList = selectBuildImages(cfg,relName,relData)
    ver, prev = getVersion()

    print("Release = {}".format(relName))
    print("Images = {}".format(imgList))
    print("Version = {}".format(ver))

    tagAttach = imgList

    # Determine if we generate a Rogue zipfile
    if 'Rogue' in relData['Types']:
        zipName = os.path.join(FirmwareDir,f'rogue_{relName}_{ver}.zip')
        buildRogueFile(zipName,cfg,ver,relName,relData,imgList)
        tagAttach.append(zipName)

    # Determine if we generate a CPSW tarball
    if 'CPSW' in relData['Types']:
        tarName = os.path.join(FirmwareDir,f'cpsw_{relName}_{ver}.tar.gz')
        buildCpswFile(tarName,cfg,ver,relName,relData,imgList)
        tagAttach.append(tarName)

    if args.push is not None:
        pushRelease(relName,ver,tagAttach,prev)

