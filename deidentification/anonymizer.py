# -*- coding: utf-8 -*-

# /!\ Disclaimer:
# Use at your own risk. Please verify your anonymization results.
# This script is not guaranteed to be complete.
# In particular, the detection of burnt-in PHI is not managed.

import hashlib
import os
import shutil
from glob import glob
from tempfile import mkdtemp

import pydicom

from deidentification import tag_lists
from deidentification.archive import is_archive, pack, unpack
from deidentification.archive import unpack_first


def anonymize_file(dicom_file_in, dicom_folder_out,
                   tags_to_keep=None, forced_values=None):
    if not os.path.exists(dicom_folder_out):
        os.makedirs(dicom_folder_out)
    dicom_file_out = os.path.join(dicom_folder_out,
                                  os.path.basename(dicom_file_in))

    anon = Anonymizer(dicom_file_in, dicom_file_out,
                      tags_to_keep, forced_values)
    anon.run()


def anonymize(dicom_in, dicom_out,
              tags_to_keep=None, forced_values=None):
    """
    Configures the Anonymizer and runs it on DICOM files.
    """
    if not os.path.exists(dicom_in):
        print("The DICOM input does not exist.")
        return

    is_dicom_in_archive = is_archive(dicom_in)
    is_dicom_out_archive = is_archive(dicom_out)
    if is_dicom_in_archive:
        wip_dicom_in = mkdtemp()
        unpack(dicom_in, wip_dicom_in)
    else:
        wip_dicom_in = os.path.abspath(dicom_in)
    if is_dicom_out_archive:
        wip_dicom_out = mkdtemp()
    else:
        wip_dicom_out = os.path.abspath(dicom_out)

    if os.path.isfile(wip_dicom_in):
        anonymize_file(wip_dicom_in, wip_dicom_out,
                       tags_to_keep, forced_values)

    elif os.path.isdir(wip_dicom_in):
        if os.path.isfile(wip_dicom_out):
            print("Since the input is a directory, an output directory is expected.")
            return
        
        for root, dirs, files in os.walk(wip_dicom_in):
            folder_out = root.replace(wip_dicom_in, wip_dicom_out)
            for name in files:
                current_file = os.path.join(root, name)
                anonymize_file(current_file, folder_out,
                               tags_to_keep, forced_values)
                
    else:
        print("The input file type is not handled by this tool.")

    if is_dicom_in_archive:
        shutil.rmtree(wip_dicom_in)
    if is_dicom_out_archive:
        pack(os.path.abspath(dicom_out),
             glob(os.path.join(wip_dicom_out, '*')))
        shutil.rmtree(wip_dicom_out)


def check_anonymize_fast(dicom_in, tags_to_keep=None, forced_values=None):
    """
    Configures the Anonymizer and runs it on one DICOM file to check if anonymization already done.
    """
        
    if not os.path.exists(dicom_in):
        print("The DICOM input does not exist.")
        return
    
    if is_archive(dicom_in):
        dicom_tmp = mkdtemp()
        wip_dicom_in = unpack_first(dicom_in, dicom_tmp)
    elif os.path.isfile(dicom_in):
        wip_dicom_in = dicom_in
    elif os.path.isdir(dicom_in):
        items_in_folder = glob.glob(os.path.join(dicom_in, '*'))
        wip_dicom_in = next(filter(os.path.isfile, items_in_folder), '')
    else:
        raise AttributeError("The dicom_in type is not handled by this tool.")
        
    if os.path.isfile(wip_dicom_in):
        anon = Anonymizer(wip_dicom_in, '',
                          tags_to_keep, forced_values)
        anon.runCheck()
    else:
        raise AttributeError("The dicom_in type is not handled by this tool.")
    
    return anon.result


def check_anonymize(dicom_in, tags_to_keep=None, forced_values=None):
    """
    Check if dicom_in is an anonymized DICOM.
    Input can be DICOM file/folder or archive of DICOM files/folder
    """
    if not os.path.exists(dicom_in):
        print("The DICOM input does not exist.")
        return
    
    if is_archive(dicom_in):
        wip_dicom_in = mkdtemp()
        unpack(dicom_in, wip_dicom_in)
    else:
        wip_dicom_in = dicom_in
        
    if os.path.isfile(wip_dicom_in):
        anon = Anonymizer(wip_dicom_in, '',
                          tags_to_keep, forced_values)
        anon.runCheck()
        return anon.result
        
    elif os.path.isdir(wip_dicom_in):
        return check_folder_anonymize(wip_dicom_in, tags_to_keep, forced_values)
    
    else:
        raise AttributeError("Input is not a data type handled.")
        

def check_folder_anonymize(dicom_folder, tags_to_keep=None, forced_values=None):
    if not os.path.isdir(dicom_folder):
        raise AttributeError('Dicom_folder input is not a folder path.')
    
    anonymized = True
    for root, dirs, files in os.walk(dicom_folder):
        for filename in files:
            anon = Anonymizer(os.path.join(root, filename), '',
                              tags_to_keep, forced_values)
            anon.runCheck()
            anonymized *= anon.result
    return bool(anonymized)


class Anonymizer():

    """
    Anonymizes a DICOM file according to DICOM standard.
    """

    def __init__(self, dicom_filein, dicom_fileout,
                 tags_to_keep=None, forced_values=None):
        """
        dicom_filein: the DICOM file to anonymize
        dicom_fileout: the file to write the output of the anonymization
        tags_to_keep: a list with tags that need to be kept
        forced_values: a dictionary constructed as shown here: {(0x0010,0x0010): "My forced patient name"}
        When a tag is in forced_values, it will be kept whether or not in tags_to_keep.
        """
        self._dicom_filein = dicom_filein
        self._dicom_fileout = dicom_fileout
        self._tags_to_keep = tags_to_keep
        self._forced_values = forced_values
        self.originalDict = {}
        self.outputDict = {}
        self.result = None

    def run(self):
        """
        Reads the DICOM file, anonymizes it and write the result.
        """
        try:
            ds = pydicom.read_file(self._dicom_filein)
            try:
                meta_data = pydicom.filereader.read_file_meta_info(
                    self._dicom_filein)
                if meta_data[0x0002, 0x0002].value == "Media Storage Directory Storage":
                    print("This file is a DICOMDIR:", self._dicom_filein)
                    return
            except:
                pass
            ds.walk(self.anonymize)
        except:
            print("This file is not a DICOM file:", self._dicom_filein)
            return

        try:
            pydicom.write_file(self._dicom_fileout, ds)
        except:
            print("The anonymization fails on", self._dicom_filein)
            return
    
    def runCheck(self):
        """
        Reads the DICOM file, check anonymization.
        """
        try:
            ds = pydicom.read_file(self._dicom_filein)
            try:
                meta_data = pydicom.filereader.read_file_meta_info(
                    self._dicom_filein)
                if meta_data[0x0002, 0x0002].value == "Media Storage Directory Storage":
                    print("This file is a DICOMDIR:", self._dicom_filein)
                    return
            except:
                pass
            ds.walk(self.anonymizeCheck)
        except:
            print("This file is not a DICOM file:", self._dicom_filein)
            return

        if self.originalDict == self.outputDict:
            self.result = True
            # print('Anonymization already done')
        else:
            self.result = False
            # print('Anonymization NOT already done')

    def anonymizeCheck(self, ds, data_element):
        """
        Check anonymization on a single DICOM element.
        ds: the DICOM descriptor
        data_element: the current element to anonymize
        """
        group = data_element.tag.group
        element = data_element.tag.element
        
        # Check if the value must be forced
        if self._forced_values is not None and \
        (group, element) in list(self._forced_values.keys()):
            self.originalDict[data_element.tag] = data_element.value
            data_element.value = self._forced_values[(group, element)]
            self.outputDict[data_element.tag] = self._forced_values[(group, element)]
            return
        # Check if the data element has to be kept
        if self._tags_to_keep is not None and \
        (group, element) in self._tags_to_keep:
            self.originalDict[data_element.tag] = data_element.value
            self.outputDict[data_element.tag] = data_element.value
            return
        # Check if the data element is in the DICOM part 15/annex E tag list
        if (group, element) in list(tag_lists.annex_e.keys()):
            # Apply the recommended action
            action = tag_lists.annex_e[(group, element)][2][0]
            if 'X' == action:
                del ds[data_element.tag]
            elif 'Z' == action:
                self.originalDict[data_element.tag] = data_element.value
                data_element.value = ""
                self.outputDict[data_element.tag] = data_element.value
            elif 'D' == action:
                self.originalDict[data_element.tag] = data_element.value
                data_element.value = self._get_cleaned_value(data_element)
                self.outputDict[data_element.tag] = data_element.value
            elif 'U' == action:
                data_element.value = self._generate_uuid(data_element.value.encode())
        # Check if the data element is private
        elif data_element.tag.is_private:
            if self._is_private_creator(group, element):
                self.originalDict[data_element.tag] = data_element.value
                self.outputDict[data_element.tag] = data_element.value
                return
            private_creator_value = ds.get(
                self._get_private_creator_tag(data_element), None).value
            # Check if the private creator is in the safe private attribute
            # keys
            if private_creator_value not in list(tag_lists.safe_private_attributes.keys()):
                self.originalDict[data_element.tag] = data_element.value
                self.outputDict[data_element.tag] = data_element.value
                return
            block = element & 0x00ff
            # Check if the data element is in the safe private attributes list
            if (group, block) not in tag_lists.safe_private_attributes[private_creator_value]:
                del ds[data_element.tag]
        #else:
            #self.originalDict[data_element.tag] = data_element.value
            #self.outputDict[data_element.tag] = data_element.value
                
    def anonymize(self, ds, data_element):
        """
        Anonymizes a single DICOM element.
        ds: the DICOM descriptor
        data_element: the current element to anonymize
        """
        group = data_element.tag.group
        element = data_element.tag.element
        # Check if the value must be forced
        if self._forced_values is not None and \
        (group, element) in list(self._forced_values.keys()):
            data_element.value = self._forced_values[(group, element)]
            return
        # Check if the data element has to be kept
        if self._tags_to_keep is not None and \
        (group, element) in self._tags_to_keep:
            return
        # Check if the data element is in the DICOM part 15/annex E tag list
        if (group, element) in list(tag_lists.annex_e.keys()):
            # Apply the recommended action
            action = tag_lists.annex_e[(group, element)][2][0]
            if 'X' == action:
                del ds[data_element.tag]
            elif 'Z' == action:
                data_element.value = ""
            elif 'D' == action:
                data_element.value = self._get_cleaned_value(data_element)
            elif 'U' == action:
                data_element.value = self._generate_uuid(data_element.value.encode())
        # Check if the data element is private
        elif data_element.tag.is_private:
            if self._is_private_creator(group, element):
                return
            try:
                private_creator_value = ds.get(
                    self._get_private_creator_tag(data_element), None).value
            except:
                print('The tag ' + str(data_element.tag) + ' does not exist in this sequence.')
                return
            # Check if the private creator is in the safe private attribute
            # keys
            if private_creator_value not in list(tag_lists.safe_private_attributes.keys()):
                return
            block = element & 0x00ff
            # Check if the data element is in the safe private attributes list
            if (group, block) not in tag_lists.safe_private_attributes[private_creator_value]:
                del ds[data_element.tag]
            
    def _generate_uuid(self, input):
        """
        Returns an UUID according to input.
        """
        return hashlib.md5(input).hexdigest()

    def _get_cleaned_value(self, data_element):
        """
        Gets a cleaned value of data_element value according to its representation.
        """
        if data_element.VR == 'UI':
            return self._generate_uuid(data_element.value)
        if data_element.VR == 'DT' or data_element.VR == 'TM':
            return "000000.00"
        elif data_element.VR == 'DA':
            return "20000101"
        return "no value"

    def _is_private_creator(self, group, element):
        """
        Returns true if the (group, element) tag is a private creator and false otherwise.
        """
        return group % 2 != 0 and \
            element > 0x0000 and element < 0x00ff

    def _get_private_creator_tag(self, data_element):
        """
        Gets the private creator tag of data_element.
        """
        group = data_element.tag.group
        element = (data_element.tag.element & 0xff00) >> 8
        return pydicom.tag.Tag(group, element)
